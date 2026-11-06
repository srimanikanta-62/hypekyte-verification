"""Legitimacy scoring: independent signals -> Existence + Association -> status.

Two questions, scored separately:
  Existence   (max 60)  Does this business really exist and operate?
  Association (max 40)  Is the applicant actually linked to it?

VERIFIED requires BOTH: existence >= 20 (one authoritative source fully agrees) AND
association >= 30 (the applicant proved control of a phone number that an *independent*
source - the GST register or the Google listing - ties to this business), with no
conflicts ("caps"). Anything that conflicts is routed to a human (NEEDS_REVIEW) rather
than auto-rejected, because most conflicts have innocent explanations (branches, brand vs
legal name, an accountant's phone on the GST record). UNVERIFIED is reserved for cases
where nothing establishes the business, or a source says it is shut / invalid.
"""

from __future__ import annotations

from matching import (address_similarity, best_name_similarity, category_consistent,
                      haversine_m, is_indian_mobile, mask_phone, name_verdict, normalize,
                      same_state)

EXISTENCE_MAX, ASSOCIATION_MAX = 60, 40
VERIFY_EXISTENCE, VERIFY_ASSOCIATION = 20, 30
ON_SITE_M, FAR_AWAY_M, PRECISE_M = 150, 2000, 200
ESTABLISHED_REVIEWS = 25


class Signal(dict):
    pass


def _sig(sid, group, source, label, outcome, points, detail, mode=None):
    return Signal(id=sid, group=group, source=source, label=label, outcome=outcome,
                  points=points, detail=detail, mode=mode)


def _locality_words(place: dict | None) -> set[str]:
    if not place:
        return set()
    words = set()
    for key in ("city", "state"):
        words |= set(normalize(place.get(key)).split())
    for part in (place.get("short_address") or "").split(","):
        words |= set(normalize(part).split())
    return {w for w in words if not w.isdigit()}


def _gst_names(record: dict) -> list[str]:
    return [n for n in (record.get("trade_name"), record.get("legal_name")) if n]


def evaluate(state: dict, prior_claims: list[dict] | None = None) -> dict:
    signals: list[Signal] = []
    caps: list[str] = []          # anything here blocks VERIFIED
    hard: list[str] = []          # anything here forces UNVERIFIED
    deductions: list[dict] = []   # conflicts also lower the score, weighted by severity
    penalty = 0

    def cap(message: str, points: int) -> None:
        caps.append(message)
        if points:
            deductions.append({"reason": message, "points": points})

    name = state.get("business_name")
    typed_name = state.get("name_source") == "typed"
    place = state.get("place")
    gst = state.get("gst") or {}
    record = gst.get("record") if gst.get("confirmed") is not False else None
    gst_error = gst.get("error")
    gst_active = bool(record and str(record.get("status", "")).lower() == "active")
    phone = state.get("phone") or {}
    otp = state.get("otp") or {}
    presence = state.get("presence") or {}

    # ------------------------------------------------------------ EXISTENCE
    if not gst:
        signals.append(_sig("gst", "existence", "GST registry", "GST registration", "skip", 0,
                            "No GSTIN given. It's optional, but it is the strongest proof of existence."))
    elif gst_error in ("GSTIN_INVALID_FORMAT", "GSTIN_INVALID_CHECKSUM"):
        signals.append(_sig("gst", "existence", "GST registry", "GST registration", "fail", 0,
                            f"{gst.get('gstin')} is not a valid GSTIN (format/checksum check failed).",
                            "offline"))
        cap("The GSTIN submitted was invalid.", 10)
    elif gst_error == "GSTIN_NOT_FOUND":
        signals.append(_sig("gst", "existence", "GST registry", "GST registration", "fail", 0,
                            f"{gst.get('gstin')} is well-formed but is not on the GST register.", "live"))
        cap("The GSTIN submitted is not registered.", 10)
    elif gst_error:
        signals.append(_sig("gst", "existence", "GST registry", "GST registration", "warn", 0,
                            "The GST registry could not be reached, so registration is unchecked.", "live"))
        cap("GST registry check could not be completed. Retry or review manually.", 0)
    elif gst.get("confirmed") is False:
        signals.append(_sig("gst", "existence", "GST registry", "GST registration", "info", 0,
                            "The applicant said the GST record shown was not their business, so it was ignored."))
    elif record and gst_active:
        mode = record.get("mode")
        signals.append(_sig("gst", "existence", "GST registry", "GST registration", "pass", 30,
                            f"Active GST registration since {record.get('registration_date') or 'n/a'} "
                            f"({record.get('taxpayer_type') or 'taxpayer'}).", mode))
        if record.get("test"):
            cap("GST data came from the provider's sandbox (test record), not the real register.", 0)
    elif record:
        signals.append(_sig("gst", "existence", "GST registry", "GST registration", "fail", 0,
                            f"GST registration status is '{record.get('status')}'"
                            + (f" (cancelled {record['cancellation_date']})." if record.get("cancellation_date") else "."),
                            record.get("mode")))
        cap(f"GST registration is {record.get('status')}, not Active.", 15)

    if place:
        status = place.get("business_status") or "OPERATIONAL"
        if status == "CLOSED_PERMANENTLY":
            signals.append(_sig("listing", "existence", "Google Places", "Google Maps listing", "fail", 0,
                                "Google marks this business as permanently closed.", "live"))
            hard.append("Google Maps marks the selected business as permanently closed.")
        elif status == "CLOSED_TEMPORARILY":
            signals.append(_sig("listing", "existence", "Google Places", "Google Maps listing", "warn", 5,
                                "Listing found but marked temporarily closed.", "live"))
            cap("The Google listing is marked temporarily closed.", 5)
        else:
            signals.append(_sig("listing", "existence", "Google Places", "Google Maps listing", "pass", 20,
                                f"Operating listing: {place.get('name')}, {place.get('short_address') or place.get('address')}.",
                                "live"))
        reviews = place.get("rating_count") or 0
        if reviews >= ESTABLISHED_REVIEWS:
            signals.append(_sig("maturity", "existence", "Google Places", "Established listing", "pass", 5,
                                f"{reviews:,} public reviews"
                                + (f", rated {place['rating']}" if place.get("rating") else "")
                                + ". Long-lived listings are hard to fabricate.", "live"))
        else:
            signals.append(_sig("maturity", "existence", "Google Places", "Established listing", "info", 0,
                                f"Only {reviews} reviews, so this is a new or rarely visited listing.", "live"))
    elif state.get("not_on_google"):
        signals.append(_sig("listing", "existence", "Google Places", "Google Maps listing", "skip", 0,
                            "Applicant says the business is not on Google Maps."))
    else:
        signals.append(_sig("listing", "existence", "Google Places", "Google Maps listing", "skip", 0,
                            "No Google listing was linked."))

    # GST <-> Google cross-check (independent sources agreeing is the strongest existence evidence)
    ledger_cross = {}
    if record and place:
        stop = _locality_words(place)
        gst_vs_place, _ = best_name_similarity(place.get("name"), _gst_names(record), stop)
        verdict = name_verdict(gst_vs_place)
        branch_pins = {str(a.get("pincode")) for a in record.get("additional_addresses") or [] if a.get("pincode")}
        pin_equal = bool(record.get("pincode") and place.get("pincode") and str(record["pincode"]) == str(place["pincode"]))
        pin_branch = bool(place.get("pincode") and place["pincode"] in branch_pins)
        state_ok = same_state(record.get("state_code"), place.get("state"))
        ledger_cross = {"name_score": gst_vs_place, "pin_equal": pin_equal or pin_branch, "state_ok": state_ok}

        if state_ok is False:
            signals.append(_sig("cross", "existence", "GST × Google", "Registry matches listing", "fail", 0,
                                f"GST is registered in {record.get('state')} but the listing is in {place.get('state')}.",
                                record.get("mode")))
            cap("GST state and Google listing state differ.", 15)
        elif verdict == "mismatch":
            signals.append(_sig("cross", "existence", "GST × Google", "Registry matches listing", "fail", 0,
                                f"GST name ({record.get('trade_name') or record.get('legal_name')}) and listing name "
                                f"({place.get('name')}) look like different businesses ({gst_vs_place}%).",
                                record.get("mode")))
            cap("GST registered name and Google listing name don't match.", 15)
        elif pin_equal or pin_branch:
            signals.append(_sig("cross", "existence", "GST × Google", "Registry matches listing",
                                "pass" if verdict == "match" else "warn", 10 if verdict == "match" else 5,
                                f"Names agree ({gst_vs_place}%) and PIN {place.get('pincode')} matches the "
                                + ("registered branch." if pin_branch and not pin_equal else "registered address."),
                                record.get("mode")))
        else:
            signals.append(_sig("cross", "existence", "GST × Google", "Registry matches listing", "warn", 0,
                                f"Names agree but the GST PIN ({record.get('pincode')}) differs from the listing PIN "
                                f"({place.get('pincode')}). It could be another branch.", record.get("mode")))
            cap("GST registered PIN differs from the Google listing's PIN (branch?).", 5)

    # ------------------------------------------------------------ CONSISTENCY
    if typed_name and name:
        if place:
            s, _ = best_name_similarity(name, [place.get("name")], _locality_words(place))
            v = name_verdict(s)
            if v == "mismatch":
                signals.append(_sig("name_listing", "consistency", "You × Google", "Name matches listing", "fail", 0,
                                    f"'{name}' vs '{place.get('name')}' ({s}%).", "live"))
                cap("The business name entered doesn't match the selected Google listing.", 10)
            else:
                signals.append(_sig("name_listing", "consistency", "You × Google", "Name matches listing",
                                    "pass" if v == "match" else "warn", 0, f"'{name}' vs '{place.get('name')}' ({s}%).",
                                    "live"))
        if record:
            s, best = best_name_similarity(name, _gst_names(record))
            v = name_verdict(s)
            if v == "mismatch":
                signals.append(_sig("name_gst", "consistency", "You × GST", "Name matches GST record", "fail", 0,
                                    f"'{name}' vs registered '{record.get('trade_name') or record.get('legal_name')}' ({s}%).",
                                    record.get("mode")))
                cap("The business name entered differs from the GST registered name.", 10)
            else:
                signals.append(_sig("name_gst", "consistency", "You × GST", "Name matches GST record",
                                    "pass" if v == "match" else "warn", 0, f"'{name}' vs '{best}' ({s}%).",
                                    record.get("mode")))

    category = state.get("category")
    if place and category:
        consistent = category_consistent(category, place.get("types"))
        if consistent is False:
            penalty += 5
            signals.append(_sig("category", "consistency", "You × Google", "Category matches listing", "warn", -5,
                                f"You chose {category}, but Google lists it as {place.get('type_label') or place.get('primary_type')}.",
                                "live"))
        elif consistent:
            signals.append(_sig("category", "consistency", "You × Google", "Category matches listing", "pass", 0,
                                f"{category} is consistent with '{place.get('type_label') or place.get('primary_type')}'.", "live"))

    similar = state.get("similar") or []
    lookalikes = [s for s in similar if s.get("is_lookalike")]
    listing_phone_proven = otp.get("verified") and phone.get("source") == "places"
    cross_ok = bool(ledger_cross.get("pin_equal") and (ledger_cross.get("name_score") or 0) >= 85)
    if place and lookalikes:
        resolved = listing_phone_proven or cross_ok
        def _where(s):
            d = s.get("distance_m") or 0
            far = f"{d / 1000:.1f} km" if d >= 1000 else f"{d} m"
            return f"{s['name']} ({far} away" + (", same PIN)" if s.get("same_pin") else ")")
        names = "; ".join(_where(s) for s in lookalikes[:3])
        signals.append(_sig("lookalikes", "consistency", "Google Places", "Unique listing",
                            "pass" if resolved else "warn", 0,
                            f"{len(lookalikes)} similar listing(s) in the same area: {names}. "
                            + ("Resolved: the applicant proved control of this listing's own phone."
                               if listing_phone_proven else
                               "Resolved: the GST address pins this exact listing." if resolved else
                               "Nothing yet proves which one is the applicant's."), "live"))
        if not resolved:
            cap("Several similar businesses share this area and nothing ties the applicant to this one.", 10)
    elif place:
        signals.append(_sig("lookalikes", "consistency", "Google Places", "Unique listing", "pass", 0,
                            "No look-alike businesses nearby.", "live"))

    for claim in prior_claims or []:
        which = "GSTIN" if claim.get("gstin") and claim.get("gstin") == (record or {}).get("gstin") else "Google listing"
        signals.append(_sig(f"dup-{claim['id']}", "consistency", "HypeKyte records", "Not already claimed", "fail", 0,
                            f"This {which} was already verified for registration #{claim['id']} "
                            f"('{claim['business_name']}').", "live"))
        cap(f"The same {which} is already verified on another HypeKyte account.", 20)

    tried = {h.get("gstin") for h in state.get("gst_history") or [] if h.get("gstin")}
    if len(tried) >= 3:
        signals.append(_sig("gst_fishing", "consistency", "HypeKyte records", "GSTIN attempts", "warn", 0,
                            f"{len(tried)} different GSTINs were tried in this session.", None))
        cap("Multiple different GSTINs were tried in one session.", 10)

    # ------------------------------------------------------------ ASSOCIATION
    source = phone.get("source")
    if otp.get("verified"):
        mode = "simulated"
        if source == "gst":
            contact_mode = (state.get("gst_contact") or {}).get("mode")
            signals.append(_sig("otp", "association", "GST registry + OTP", "Controls GST-registered mobile", "pass", 40,
                                f"Applicant knew and received an OTP on the mobile filed with GST ({mask_phone(phone.get('number'))}). "
                                f"GST contact: {contact_mode}; OTP delivery: simulated.", mode))
        elif source == "places":
            signals.append(_sig("otp", "association", "Google Places + OTP", "Controls Google-listed phone", "pass", 30,
                                f"Applicant knew and received an OTP on the phone published on the Google listing "
                                f"({mask_phone(phone.get('number'))}).", mode))
        else:
            signals.append(_sig("otp", "association", "OTP", "Controls a phone number", "info", 5,
                                f"OTP confirmed on {mask_phone(phone.get('number'))}. No source ties this number to the "
                                "business, so it only proves the applicant is reachable.", mode))
    else:
        signals.append(_sig("otp", "association", "OTP", "Phone control", "fail", 0,
                            "No phone number was verified by OTP.", None))

    fails = state.get("phone_failures") or {}
    if fails.get("gst", 0) >= 3:
        signals.append(_sig("gst_phone_miss", "association", "GST registry", "GST mobile known", "info", 0,
                            "Applicant could not supply the GST-registered mobile. This is common when an accountant filed the GST.",
                            None))
    if fails.get("places", 0) >= 3:
        signals.append(_sig("places_phone_miss", "association", "Google Places", "Listing phone known", "warn", 0,
                            "Applicant could not supply the phone number published on their own Google listing.", "live"))
    if place and place.get("phone_national") and not is_indian_mobile(place.get("phone_national"), place.get("phone_international")) \
            and source != "places":
        signals.append(_sig("landline", "association", "Google Places", "Listing phone reachable by SMS", "info", 0,
                            f"The listing's number ({place.get('phone_national')}) is a landline, so it can't receive an SMS code.",
                            "live"))

    if presence.get("at_business") and (presence.get("lat") is not None or not presence.get("precise")):
        target = place or (record or {}).get("_located")
        if not presence.get("precise"):
            signals.append(_sig("presence", "association", "Device location", "On-site check", "info", 0,
                                f"Location was too imprecise (±{int(presence.get('accuracy') or 0)} m) to count.", "live"))
        elif target and target.get("lat") is not None:
            d = haversine_m(presence["lat"], presence["lng"], target["lat"], target["lng"])
            if d <= ON_SITE_M:
                signals.append(_sig("presence", "association", "Device location", "On-site check", "pass", 10,
                                    f"Device was {int(d)} m from the business when registering.", "live"))
            elif d > FAR_AWAY_M:
                signals.append(_sig("presence", "association", "Device location", "On-site check", "fail", 0,
                                    f"Applicant said they were at the business, but the device was {d / 1000:.1f} km away.",
                                    "live"))
                cap("Applicant claimed to be on-site but was far from the business.", 15)
            else:
                signals.append(_sig("presence", "association", "Device location", "On-site check", "info", 0,
                                    f"Device was {int(d)} m away: nearby, but not on-site.", "live"))

    # ------------------------------------------------------------ DECISION
    existence = min(EXISTENCE_MAX, sum(s["points"] for s in signals if s["group"] == "existence" and s["points"] > 0))
    association = min(ASSOCIATION_MAX, sum(s["points"] for s in signals if s["group"] == "association" and s["points"] > 0))
    penalty += sum(d["points"] for d in deductions)
    # Lead with the most serious conflict (stable for equal weights).
    weight = {d["reason"]: d["points"] for d in deductions}
    caps = sorted(caps, key=lambda m: -weight.get(m, 0))
    score = max(0, min(100, existence + association - penalty))

    if hard:
        status, headline = "UNVERIFIED", hard[0]
    elif existence == 0:
        status = "UNVERIFIED"
        headline = (caps[0] if caps else "No independent source could establish that this business exists.")
    elif caps:
        status, headline = "NEEDS_REVIEW", caps[0]
    elif existence < VERIFY_EXISTENCE:
        status, headline = "NEEDS_REVIEW", "Existence evidence is too thin for automatic approval."
    elif association < VERIFY_ASSOCIATION:
        status = "NEEDS_REVIEW"
        headline = ("The business checks out, but nothing yet links the applicant to it. "
                    "Their phone isn't one the GST record or Google listing holds.")
    else:
        status = "VERIFIED"
        via = "GST-registered mobile" if source == "gst" else "Google-listed phone"
        sources = " and ".join(x for x in (["the GST register"] if gst_active else []) +
                               (["Google Maps"] if place else []))
        headline = f"Confirmed by {sources}, and the applicant controls the business's {via}."

    return {
        "status": status,
        "score": score,
        "existence": existence,
        "association": association,
        "penalty": penalty,
        "deductions": ([{"reason": "Category differs from the Google listing.", "points": 5}]
                       if any(s["id"] == "category" and s["points"] < 0 for s in signals) else []) + deductions,
        "headline": headline,
        "signals": signals,
        "caps": caps,
        "hard_fails": hard,
        "ledger": _ledger(state, record, place, ledger_cross),
        "thresholds": {"existence": VERIFY_EXISTENCE, "association": VERIFY_ASSOCIATION,
                       "existence_max": EXISTENCE_MAX, "association_max": ASSOCIATION_MAX},
    }


def _ledger(state: dict, record: dict | None, place: dict | None, cross: dict) -> list[dict]:
    phone = state.get("phone") or {}
    contact = state.get("gst_contact") or {}
    rows = [
        {"field": "Business name", "submitted": state.get("business_name"),
         "gst": " / ".join(_gst_names(record)) if record else None,
         "google": place.get("name") if place else None,
         "note": f"GST × Google {cross['name_score']}%" if cross.get("name_score") is not None else None},
        {"field": "Address", "submitted": state.get("manual_address"),
         "gst": record.get("address") if record else None,
         "google": place.get("address") if place else None,
         "note": (f"{address_similarity(record.get('address'), place.get('address'))}% overlap"
                  if record and place and record.get("address") else None)},
        {"field": "PIN code", "submitted": None,
         "gst": record.get("pincode") if record else None,
         "google": place.get("pincode") if place else None,
         "note": ("match" if cross.get("pin_equal") else "differs") if cross else None},
        {"field": "State", "submitted": None,
         "gst": record.get("state") if record else None,
         "google": place.get("state") if place else None,
         "note": ({True: "match", False: "differs"}.get(cross.get("state_ok"))) if cross else None},
        {"field": "Phone", "submitted": mask_phone(phone.get("number")) if phone.get("number") else None,
         "gst": mask_phone(contact.get("mobile")) if contact.get("found") else None,
         "google": place.get("phone_national") if place else None,
         "note": ("OTP verified" if (state.get("otp") or {}).get("verified") else None)},
        {"field": "Category", "submitted": state.get("category"),
         "gst": ", ".join(record.get("nature_of_business") or []) or None if record else None,
         "google": (place.get("type_label") or place.get("primary_type")) if place else None, "note": None},
        {"field": "Status", "submitted": None,
         "gst": record.get("status") if record else None,
         "google": place.get("business_status") if place else None, "note": None},
    ]
    return [r for r in rows if r["submitted"] or r["gst"] or r["google"]]
