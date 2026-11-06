"""HypeKyte Business Verification API.

A verification is a server-side *session* that accumulates evidence step by step
(location, Google listing, GSTIN, phone + OTP). Full phone numbers, OTP hashes and
raw coordinates never leave the server; the client only ever sees `public_view()`.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Callable, Literal

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import database
import google_places as places
import gstin as gst
import otp
from config import CORS_ORIGINS, GST_CONTACT_MODE, OTP_MODE, SANDBOX_GSTIN, ApiError
from matching import (AUTOCOMPLETE_TYPES, CATEGORIES, best_name_similarity, claim_matches,
                      extract_pincode, haversine_m, infer_category, is_indian_mobile,
                      matched_words, phone_digits, phone_hint)
from scoring import PRECISE_M, evaluate

MAX_PHONE_ATTEMPTS = 3


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.create_tables()
    yield


app = FastAPI(title="HypeKyte Business Verification API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ApiError)
async def api_error_handler(_, exc: ApiError):
    return JSONResponse(status_code=exc.status,
                        content={"code": exc.code, "message": exc.message, **exc.extra})


# ====================================================================== helpers
def _load(session_id: str) -> dict:
    state = database.load_session(session_id)
    if state is None:
        raise ApiError("SESSION_NOT_FOUND", "This verification session has expired. Start again.", 404)
    if state.get("verification_id"):
        raise ApiError("SESSION_FINALIZED", "This verification is already submitted.", 409,
                       verification_id=state["verification_id"])
    return state


def _mutate(session_id: str, fn: Callable[[dict], dict | None]) -> dict:
    """Run fn on the session; persist even when fn raises (attempt counters must stick)."""
    state = _load(session_id)
    try:
        extra = fn(state) or {}
    except ApiError as exc:
        database.save_session(session_id, state)
        exc.extra["session"] = public_view(state)
        raise
    database.save_session(session_id, state)
    return {"session": public_view(state), **extra}


def _prior_claims(state: dict) -> list[dict]:
    record = (state.get("gst") or {}).get("record") or {}
    gstin_value = record.get("gstin") if (state.get("gst") or {}).get("confirmed") else None
    place_id = (state.get("place") or {}).get("place_id")
    return database.find_prior_claims(gstin_value, place_id, state["id"])


def _public_place(place: dict | None) -> dict | None:
    if not place:
        return None
    hidden = {"phone_national", "phone_international"}
    out = {k: v for k, v in place.items() if k not in hidden}
    number = place.get("phone_national")
    out["phone"] = {
        "listed": bool(number),
        "hint": phone_hint(number),
        "sms_capable": is_indian_mobile(number, place.get("phone_international")) if number else False,
        "display": number if number and not is_indian_mobile(number, place.get("phone_international")) else None,
    }
    return out


def phone_targets(state: dict) -> list[dict]:
    """Phone numbers the applicant can prove control of, strongest first."""
    targets = []
    fails = state.get("phone_failures") or {}
    gst_state = state.get("gst") or {}
    contact = state.get("gst_contact") or {}
    if gst_state.get("confirmed") and contact.get("found"):
        number = contact.get("mobile")
        targets.append({"source": "gst", "label": "Mobile registered with GST", "hint": phone_hint(number),
                        "sms_capable": is_indian_mobile(number), "mode": contact.get("mode"),
                        "exhausted": fails.get("gst", 0) >= MAX_PHONE_ATTEMPTS, "points": 40})
    place = state.get("place")
    if place and place.get("phone_national"):
        number = place["phone_national"]
        targets.append({"source": "places", "label": "Phone on your Google listing", "hint": phone_hint(number),
                        "sms_capable": is_indian_mobile(number, place.get("phone_international")),
                        "display": None if is_indian_mobile(number, place.get("phone_international")) else number,
                        "mode": "live", "exhausted": fails.get("places", 0) >= MAX_PHONE_ATTEMPTS, "points": 30})
    targets.append({"source": "self", "label": "Your own mobile", "hint": None, "sms_capable": True,
                    "mode": None, "exhausted": False, "points": 5})
    return targets


def public_view(state: dict) -> dict:
    gst_state = state.get("gst")
    public_gst = None
    if gst_state:
        record = gst_state.get("record")
        public_gst = {
            "gstin": gst_state.get("gstin"),
            "decoded": gst.decode(gst_state.get("gstin") or ""),
            "error": gst_state.get("error"),
            "confirmed": gst_state.get("confirmed"),
            "record": ({k: v for k, v in record.items() if not k.startswith("_")} if record else None),
            "highlight": gst_state.get("highlight"),
            "name_score": gst_state.get("name_score"),
            "contact": ({"found": (state.get("gst_contact") or {}).get("found"),
                         "mode": (state.get("gst_contact") or {}).get("mode"),
                         "note": (state.get("gst_contact") or {}).get("note")}
                        if state.get("gst_contact") else None),
        }
    phone = state.get("phone") or {}
    otp_state = state.get("otp") or {}
    presence = state.get("presence") or {}
    preview = evaluate(state, _prior_claims(state))
    return {
        "id": state["id"],
        "business_name": state.get("business_name"),
        "name_source": state.get("name_source"),
        "category": state.get("category"),
        "category_source": state.get("category_source"),
        "presence": ({"at_business": presence.get("at_business"), "precise": presence.get("precise"),
                      "accuracy": presence.get("accuracy")} if presence else None),
        "place": _public_place(state.get("place")),
        "place_source": state.get("place_source"),
        "similar": state.get("similar") or [],
        "not_on_google": state.get("not_on_google", False),
        "manual_address": state.get("manual_address"),
        "gst": public_gst,
        "phone_targets": phone_targets(state),
        "phone": ({"source": phone.get("source"), "matched": phone.get("matched", False),
                   "hint": phone_hint(phone.get("number")) if phone.get("number") else None}
                  if phone else None),
        "phone_failures": state.get("phone_failures") or {},
        "otp": ({"sent": True, "verified": otp_state.get("verified", False),
                 "expires_at": otp_state.get("expires_at"), "resend_at": otp_state.get("sent_at", 0) + otp.RESEND_COOLDOWN_S,
                 "attempts_left": otp.MAX_VERIFY_ATTEMPTS - otp_state.get("attempts", 0)}
                if otp_state else None),
        "preview": {k: preview[k] for k in ("status", "score", "existence", "association", "headline", "caps")}
                   | {"signals": [{k: s[k] for k in ("id", "group", "label", "outcome", "points", "source")}
                                  for s in preview["signals"]]},
        "modes": {"otp": OTP_MODE, "gst_contact": GST_CONTACT_MODE},
    }


def _find_similar(place: dict) -> list[dict]:
    """Look-alike businesses near the chosen listing (scenario: several similar names)."""
    if place.get("lat") is None or not place.get("name"):
        return []
    query = place["name"].split(" - ")[0]
    try:
        results = places.text_search(query, place["lat"], place["lng"], radius_m=3000, page_size=10)
    except ApiError:
        return []
    out = []
    for r in results:
        if r["place_id"] == place["place_id"] or r.get("lat") is None:
            continue
        score, _ = best_name_similarity(place["name"], [r["name"]])
        distance = haversine_m(place["lat"], place["lng"], r["lat"], r["lng"])
        same_pin = bool(place.get("pincode") and extract_pincode(r.get("address")) == place["pincode"])
        if (score or 0) >= 85 and distance <= 5000:
            out.append({"place_id": r["place_id"], "name": r["name"], "short_address": r.get("short_address"),
                        "distance_m": int(distance), "name_score": score, "same_pin": same_pin,
                        "is_lookalike": same_pin or distance <= 1000})
    return sorted(out, key=lambda x: x["distance_m"])[:5]


# ==================================================================== endpoints
@app.get("/")
def home():
    return {"service": app.title, "version": app.version}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/meta")
def meta():
    return {"categories": CATEGORIES, "otp_mode": OTP_MODE, "gst_contact_mode": GST_CONTACT_MODE,
            "sandbox_gstin": SANDBOX_GSTIN, "otp_length": otp.CODE_LENGTH}


class StartBody(BaseModel):
    business_name: str | None = Field(default=None, max_length=120)


@app.post("/api/sessions")
def create_session(body: StartBody | None = None):
    session_id = uuid.uuid4().hex
    state = {"id": session_id, "created_at": time.time(), "phone_failures": {}, "gst_history": []}
    if body and body.business_name:
        state["business_name"], state["name_source"] = body.business_name.strip(), "typed"
    database.insert_session(session_id, state)
    return {"session": public_view(state)}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    state = database.load_session(session_id)
    if state is None:
        raise ApiError("SESSION_NOT_FOUND", "This verification session has expired. Start again.", 404)
    return {"session": public_view(state), "verification_id": state.get("verification_id")}


class ProfileBody(BaseModel):
    business_name: str | None = Field(default=None, min_length=2, max_length=120)
    category: str | None = None


@app.post("/api/sessions/{session_id}/profile")
def set_profile(session_id: str, body: ProfileBody):
    def fn(state):
        if body.business_name is not None:
            state["business_name"], state["name_source"] = body.business_name.strip(), "typed"
        if body.category is not None:
            if body.category not in CATEGORIES:
                raise ApiError("BAD_CATEGORY", "Pick one of the listed categories.", 422)
            state["category"], state["category_source"] = body.category, "user"
    return _mutate(session_id, fn)


class PresenceBody(BaseModel):
    at_business: bool
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)


@app.post("/api/sessions/{session_id}/presence")
def set_presence(session_id: str, body: PresenceBody):
    def fn(state):
        if not body.at_business or body.lat is None or body.lng is None:
            state["presence"] = {"at_business": body.at_business}
            return {"nearby": []}
        precise = (body.accuracy or 9999) <= PRECISE_M
        state["presence"] = {"at_business": True, "lat": body.lat, "lng": body.lng,
                             "accuracy": round(body.accuracy or 0), "precise": precise}
        radius = 150.0 if precise else min(max(body.accuracy or 500, 300.0), 1500.0)
        found = places.nearby(body.lat, body.lng, radius_m=radius)
        skip = {"route", "political", "locality", "sublocality", "atm", "bus_stop", "parking"}
        nearby_list = []
        for p in found:
            if set(p["types"]) & skip or p.get("lat") is None:
                continue
            nearby_list.append({**{k: p[k] for k in ("place_id", "name", "short_address", "type_label", "primary_type")},
                                "distance_m": int(haversine_m(body.lat, body.lng, p["lat"], p["lng"]))})
        typed = state.get("business_name") if state.get("name_source") == "typed" else None
        for item in nearby_list:
            score, _ = best_name_similarity(typed, [item["name"]]) if typed else (None, None)
            item["name_match"] = bool(score and score >= 85)
        nearby_list.sort(key=lambda x: (not x["name_match"], x["distance_m"]))
        return {"nearby": nearby_list, "precise": precise}
    return _mutate(session_id, fn)


@app.get("/api/places/autocomplete")
def autocomplete(q: str = Query(min_length=2, max_length=120), token: str | None = None,
                 session_id: str | None = None, kind: Literal["business", "address"] = "business"):
    lat = lng = None
    if session_id:
        presence = (database.load_session(session_id) or {}).get("presence") or {}
        lat, lng = presence.get("lat"), presence.get("lng")
    return {"suggestions": places.autocomplete(q, token, lat, lng, addresses=(kind == "address"))}


class PlaceBody(BaseModel):
    place_id: str = Field(min_length=2, max_length=300)
    token: str | None = None
    source: Literal["nearby", "search", "gst_link"] = "search"


@app.post("/api/sessions/{session_id}/place")
def choose_place(session_id: str, body: PlaceBody):
    def fn(state):
        place = places.details(body.place_id, body.token)
        state["place"], state["place_source"] = place, body.source
        state["not_on_google"], state["manual_address"] = False, None
        state["similar"] = _find_similar(place)
        if state.get("name_source") != "typed" or not state.get("business_name"):
            state["business_name"], state["name_source"] = place.get("name"), "listing"
        if state.get("category_source") != "user":
            inferred = infer_category(place.get("primary_type"), place.get("types"))
            if inferred:
                state["category"], state["category_source"] = inferred, "inferred"
        if (state.get("phone") or {}).get("source") == "places":
            state["phone"], state["otp"] = None, None
    return _mutate(session_id, fn)


@app.delete("/api/sessions/{session_id}/place")
def clear_place(session_id: str):
    def fn(state):
        state["place"], state["similar"], state["place_source"] = None, [], None
        if state.get("name_source") == "listing":
            state["business_name"], state["name_source"] = None, None
        if state.get("category_source") == "inferred":
            state["category"], state["category_source"] = None, None
        if (state.get("phone") or {}).get("source") == "places":
            state["phone"], state["otp"] = None, None
    return _mutate(session_id, fn)


class ManualBody(BaseModel):
    address: str = Field(min_length=5, max_length=300)


@app.post("/api/sessions/{session_id}/not-on-google")
def not_on_google(session_id: str, body: ManualBody):
    def fn(state):
        state["place"], state["similar"] = None, []
        state["not_on_google"], state["manual_address"] = True, body.address.strip()
    return _mutate(session_id, fn)


class GstinBody(BaseModel):
    gstin: str = Field(min_length=1, max_length=30)


@app.post("/api/sessions/{session_id}/gstin")
def submit_gstin(session_id: str, body: GstinBody):
    def fn(state):
        value = gst.clean(body.gstin)
        state.setdefault("gst_history", []).append({"gstin": value, "at": time.time()})
        if (state.get("phone") or {}).get("source") == "gst":
            state["phone"], state["otp"] = None, None
        state["gst_contact"] = None
        state["gst"] = {"gstin": value, "record": None, "error": None, "confirmed": None}
        try:
            record = gst.lookup(value)
        except ApiError as exc:
            state["gst"]["error"] = exc.code
            state["gst_history"][-1]["outcome"] = exc.code
            raise
        state["gst"]["record"] = record
        state["gst_history"][-1]["outcome"] = record.get("status")
        names = [n for n in (record.get("trade_name"), record.get("legal_name")) if n]
        submitted = state.get("business_name")
        score, _ = best_name_similarity(submitted, names) if submitted else (None, None)
        state["gst"]["name_score"] = score
        state["gst"]["highlight"] = {n: matched_words(submitted, n) for n in names} if submitted else {}
        if not gst.is_active(record):
            raise ApiError("GSTIN_INACTIVE", f"This GST registration is {record.get('status')}.", 409)
    return _mutate(session_id, fn)


@app.delete("/api/sessions/{session_id}/gstin")
def remove_gstin(session_id: str):
    def fn(state):
        state["gst"], state["gst_contact"] = None, None
        if (state.get("phone") or {}).get("source") == "gst":
            state["phone"], state["otp"] = None, None
    return _mutate(session_id, fn)


class ConfirmBody(BaseModel):
    confirmed: bool


@app.post("/api/sessions/{session_id}/gstin/confirm")
def confirm_gstin(session_id: str, body: ConfirmBody):
    def fn(state):
        gst_state = state.get("gst") or {}
        if not gst_state.get("record"):
            raise ApiError("GSTIN_REQUIRED", "Look up a GSTIN first.", 400)
        gst_state["confirmed"] = body.confirmed
        if not body.confirmed:
            state["gst_contact"] = None
            return
        state["gst_contact"] = gst.contact(gst_state["gstin"])
        # On-site check against the GST address when no Google listing is linked.
        presence = state.get("presence") or {}
        record = gst_state["record"]
        if presence.get("precise") and not state.get("place") and record.get("address") and not record.get("test"):
            spot = places.locate(", ".join(x for x in (record.get("address"), record.get("pincode")) if x))
            if spot:
                record["_located"] = {"lat": spot["lat"], "lng": spot["lng"]}
    return _mutate(session_id, fn)


class TargetBody(BaseModel):
    source: Literal["gst", "places", "self"]


@app.post("/api/sessions/{session_id}/phone/target")
def choose_phone_target(session_id: str, body: TargetBody):
    def fn(state):
        target = next((t for t in phone_targets(state) if t["source"] == body.source), None)
        if not target:
            raise ApiError("PHONE_NOT_AVAILABLE", "That phone number isn't available for this business.", 404)
        if not target["sms_capable"]:
            raise ApiError("PHONE_NOT_SMS_CAPABLE",
                           "That number is a landline and can't receive an SMS code. Use another option.", 422)
        if target["exhausted"]:
            raise ApiError("PHONE_ATTEMPTS_EXCEEDED", "Too many wrong tries for that number. Verify another way.", 429)
        if body.source == "gst":
            number = state["gst_contact"]["mobile"]
        elif body.source == "places":
            number = state["place"]["phone_national"]
        else:
            number = None
        state["phone"] = {"source": body.source, "number": phone_digits(number) if number else None, "matched": False}
        state["otp"] = None
    return _mutate(session_id, fn)


class ClaimBody(BaseModel):
    digits: str = Field(min_length=4, max_length=16)


@app.post("/api/sessions/{session_id}/phone/claim")
def claim_phone(session_id: str, body: ClaimBody):
    def fn(state):
        phone = state.get("phone")
        if not phone:
            raise ApiError("PHONE_TARGET_REQUIRED", "Choose which number to verify first.", 400)
        source = phone["source"]
        if source == "self":
            digits = phone_digits(body.digits)
            if not is_indian_mobile(digits):
                raise ApiError("PHONE_INVALID", "Enter a 10-digit Indian mobile number.", 422)
            phone["number"] = digits
        else:
            fails = state.setdefault("phone_failures", {})
            if fails.get(source, 0) >= MAX_PHONE_ATTEMPTS:
                raise ApiError("PHONE_ATTEMPTS_EXCEEDED", "Too many wrong tries. Verify another way.", 429)
            if not claim_matches(phone["number"], body.digits):
                fails[source] = fails.get(source, 0) + 1
                left = MAX_PHONE_ATTEMPTS - fails[source]
                where = "registered with GST" if source == "gst" else "listed on your Google profile"
                if left <= 0:
                    raise ApiError("PHONE_ATTEMPTS_EXCEEDED",
                                   f"That isn't the number {where}. Let's verify another way.", 429)
                raise ApiError("PHONE_MISMATCH", f"That isn't the number {where}. {left} tr{'y' if left == 1 else 'ies'} left.",
                               409, attempts_left=left)
        phone["matched"] = True
        return {"otp": otp.send(state, session_id, phone["number"])}
    return _mutate(session_id, fn)


@app.post("/api/sessions/{session_id}/otp/resend")
def resend_otp(session_id: str):
    def fn(state):
        phone = state.get("phone") or {}
        if not phone.get("matched"):
            raise ApiError("PHONE_TARGET_REQUIRED", "Confirm the phone number first.", 400)
        return {"otp": otp.send(state, session_id, phone["number"])}
    return _mutate(session_id, fn)


class OtpBody(BaseModel):
    code: str = Field(min_length=4, max_length=8)


@app.post("/api/sessions/{session_id}/otp/verify")
def verify_otp(session_id: str, body: OtpBody):
    return _mutate(session_id, lambda state: otp.verify(state, session_id, body.code))


@app.get("/api/dev/sms/{session_id}")
def dev_inbox(session_id: str):
    if OTP_MODE != "simulated":
        raise ApiError("NOT_AVAILABLE", "The virtual phone only exists in simulated OTP mode.", 404)
    state = database.load_session(session_id)
    if state is None:
        raise ApiError("SESSION_NOT_FOUND", "Unknown session.", 404)
    return {"messages": state.get("sms_inbox", []), "simulated": True}


@app.post("/api/sessions/{session_id}/finalize")
def finalize(session_id: str):
    state = _load(session_id)
    result = evaluate(state, _prior_claims(state))
    view = public_view(state)
    place = state.get("place") or {}
    gst_state = state.get("gst") or {}
    record = gst_state.get("record") or {}
    phone = state.get("phone") or {}
    result["submission"] = {
        "business_name": state.get("business_name") or place.get("name") or record.get("trade_name") or "Unnamed business",
        "category": state.get("category"),
        "address": place.get("address") or state.get("manual_address") or record.get("address"),
        "gstin": gst_state.get("gstin"),
        "place": view["place"],
        "gst": view["gst"],
        "phone_masked": view["phone"]["hint"]["masked"] if view.get("phone") and view["phone"].get("hint") else None,
        "phone_source": phone.get("source") if (state.get("otp") or {}).get("verified") else None,
        "presence": view["presence"],
        "similar": state.get("similar") or [],
        "modes": view["modes"],
    }
    summary = {
        "business_name": result["submission"]["business_name"],
        "business_category": state.get("category"),
        "address": result["submission"]["address"],
        "gstin": record.get("gstin") if gst_state.get("confirmed") else gst_state.get("gstin"),
        "place_id": place.get("place_id"),
        "phone_masked": result["submission"]["phone_masked"],
    }
    verification_id = database.save_verification(session_id, summary, result)
    state["verification_id"] = verification_id
    # Raw coordinates are only needed while the session is live.
    if state.get("presence"):
        state["presence"].pop("lat", None)
        state["presence"].pop("lng", None)
    database.save_session(session_id, state)
    return {"verification_id": verification_id, "status": result["status"], "score": result["score"]}


@app.get("/api/verifications")
def verifications():
    return {"items": database.list_verifications()}


@app.get("/api/verifications/{verification_id}")
def verification(verification_id: int):
    record = database.get_verification(verification_id)
    if not record:
        raise ApiError("NOT_FOUND", "Verification not found.", 404)
    return record
