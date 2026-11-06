"""Test harness: isolated SQLite DB + fake Google Places and gstinapi.in providers.

Provider fakes return payloads shaped exactly like the real responses captured in
backend/samples/, so the suite exercises the real parsing, matching and scoring code
without spending API credits.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import database  # noqa: E402
import google_places  # noqa: E402
import gstin  # noqa: E402
import main  # noqa: E402


def make_gstin(prefix14: str) -> str:
    return prefix14 + gstin.checksum_char(prefix14)


# ------------------------------------------------------------------ fake data
KAVERI_GSTIN = make_gstin("29AAJCK4821M1Z")
CANCELLED_GSTIN = make_gstin("27AABCS1429B1Z")
UNREGISTERED_GSTIN = make_gstin("07AAACZ9999Q1Z")

GST_RECORDS = {
    KAVERI_GSTIN: {
        "gstin": KAVERI_GSTIN, "legal_name": "KAVERI TEXTILES PRIVATE LIMITED",
        "trade_name": "Kaveri Textiles", "status": "Active", "taxpayer_type": "Regular",
        "registration_date": "2017-07-01", "cancellation_date": None, "state_code": "29",
        "address": "No. 14, 3rd Cross, Phase II, Peenya Industrial Area, Bengaluru",
        "city": "Bengaluru", "pincode": "560058", "nature_of_business": ["Retail Business"],
        "additional_addresses": [{"address": "Jayanagar 4th Block, Bengaluru", "pincode": "560011"}],
    },
    CANCELLED_GSTIN: {
        "gstin": CANCELLED_GSTIN, "legal_name": "SHARMA SWEETS", "trade_name": "Sharma Sweets",
        "status": "Cancelled", "taxpayer_type": "Regular", "registration_date": "2018-04-01",
        "cancellation_date": "2023-03-31", "state_code": "27", "address": "Dadar West, Mumbai",
        "city": "Mumbai", "pincode": "400028", "nature_of_business": ["Retail Business"],
    },
}
CONTACTS = {KAVERI_GSTIN: {"mobile": "9876543210"}}


def _place(pid, name, lat, lng, pin, state, phone=None, intl=None, types=None, status="OPERATIONAL",
           reviews=120, primary="clothing_store"):
    return {
        "id": pid,
        "displayName": {"text": name},
        "formattedAddress": f"{name} Road, {state} {pin}, India",
        "shortFormattedAddress": f"{name} Road",
        "addressComponents": [
            {"longText": pin, "types": ["postal_code"]},
            {"longText": state, "types": ["administrative_area_level_1", "political"]},
            {"longText": "City", "types": ["locality", "political"]},
        ],
        "location": {"latitude": lat, "longitude": lng},
        "types": types or [primary, "store", "point_of_interest", "establishment"],
        "primaryType": primary,
        "primaryTypeDisplayName": {"text": primary.replace("_", " ").title()},
        "businessStatus": status,
        "nationalPhoneNumber": phone,
        "internationalPhoneNumber": intl,
        "userRatingCount": reviews,
        "rating": 4.4,
        "googleMapsUri": f"https://maps.google.com/?cid={pid}",
    }


PLACES = {
    # Kaveri Textiles - same PIN as the GST branch address, mobile listed
    "kaveri": _place("kaveri", "Kaveri Textiles", 12.9250, 77.5838, "560011", "Karnataka",
                     "098765 43210", "+91 98765 43210"),
    # Same name, PIN not on the GST record
    "kaveri_far": _place("kaveri_far", "Kaveri Textiles", 12.9900, 77.7000, "560066", "Karnataka",
                         "098450 11111", "+91 98450 11111"),
    # A café with a listed mobile, no GSTIN
    "brew": _place("brew", "Brew & Bloom Cafe", 19.0596, 72.8295, "400050", "Maharashtra",
                   "091234 56789", "+91 91234 56789", primary="cafe",
                   types=["cafe", "coffee_shop", "food", "point_of_interest", "establishment"]),
    # A restaurant whose listed phone is a landline
    "landline": _place("landline", "Annapurna Bhojnalaya", 28.6139, 77.2090, "110001", "Delhi",
                       "011 2334 5678", "+91 11 2334 5678", primary="restaurant",
                       types=["restaurant", "food", "point_of_interest", "establishment"]),
    # Two near-identical sweet shops in the same PIN
    "sweets_a": _place("sweets_a", "Gupta Sweets", 26.9124, 75.7873, "302001", "Rajasthan",
                       "093140 00001", "+91 93140 00001", primary="dessert_shop"),
    "sweets_b": _place("sweets_b", "Gupta Sweets", 26.9150, 75.7900, "302001", "Rajasthan",
                       "093140 00002", "+91 93140 00002", primary="dessert_shop"),
    "closed": _place("closed", "Old Town Electronics", 22.5726, 88.3639, "700001", "West Bengal",
                     "098300 00000", "+91 98300 00000", status="CLOSED_PERMANENTLY",
                     primary="electronics_store"),
}


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.ok = 200 <= status < 300

    def json(self):
        return self._payload


def fake_gst_request(url):
    g = url.split("/v1/gstin/")[1].split("?")[0].split("/")[0]
    if url.split("?")[0].endswith("/contact"):
        return FakeResponse(404, {"success": False})
    if g in GST_RECORDS:
        return FakeResponse(200, {"success": True, "gstin": g, "test": False, "data": GST_RECORDS[g]})
    return FakeResponse(404, {"success": False, "error": "GSTIN not found in GST database"})


def fake_details(place_id, session_token=None):
    raw = PLACES[place_id]
    comps = raw["addressComponents"]
    return {
        **google_places._summary(raw),
        "pincode": google_places._component(comps, "postal_code"),
        "state": google_places._component(comps, "administrative_area_level_1"),
        "city": google_places._component(comps, "locality"),
        "phone_national": raw.get("nationalPhoneNumber"),
        "phone_international": raw.get("internationalPhoneNumber"),
        "website": None, "maps_uri": raw["googleMapsUri"], "rating": raw["rating"],
        "rating_count": raw["userRatingCount"],
    }


def fake_text_search(query, lat=None, lng=None, radius_m=3000.0, page_size=10):
    return [google_places._summary(p) for p in PLACES.values() if query.lower() in p["displayName"]["text"].lower()]


def fake_nearby(lat, lng, radius_m=150.0, types=None):
    out = []
    for p in PLACES.values():
        s = google_places._summary(p)
        if abs(s["lat"] - lat) < 0.002 and abs(s["lng"] - lng) < 0.002:
            out.append(s)
    return out


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "test.db")
    monkeypatch.setattr(gstin, "_request", fake_gst_request)
    monkeypatch.setattr(gstin, "_fixture_contacts", lambda: CONTACTS)
    monkeypatch.setattr(gstin, "GST_CONTACT_MODE", "simulated")
    monkeypatch.setattr(google_places, "details", fake_details)
    monkeypatch.setattr(google_places, "text_search", fake_text_search)
    monkeypatch.setattr(google_places, "nearby", fake_nearby)
    monkeypatch.setattr(google_places, "locate", lambda address: None)
    database.create_tables()
    with TestClient(main.app) as c:
        yield c


class Flow:
    """Drives one verification session through the API like the frontend does."""

    def __init__(self, client, name=None):
        self.c = client
        body = {"business_name": name} if name else {}
        self.sid = self.c.post("/api/sessions", json=body).json()["session"]["id"]

    def post(self, path, body=None, expect=200):
        r = self.c.post(f"/api/sessions/{self.sid}{path}", json=body or {})
        assert r.status_code == expect, (path, r.status_code, r.json())
        return r.json()

    def place(self, pid, source="search"):
        return self.post("/place", {"place_id": pid, "source": source})

    def gstin(self, value, expect=200):
        return self.post("/gstin", {"gstin": value}, expect)

    def confirm(self, yes=True):
        return self.post("/gstin/confirm", {"confirmed": yes})

    def otp_on(self, source, digits, expect_claim=200):
        self.post("/phone/target", {"source": source})
        claim = self.post("/phone/claim", {"digits": digits}, expect_claim)
        if expect_claim != 200:
            return claim
        inbox = self.c.get(f"/api/dev/sms/{self.sid}").json()["messages"]
        code = inbox[-1]["body"][:4]
        return self.post("/otp/verify", {"code": code})

    def finalize(self):
        out = self.c.post(f"/api/sessions/{self.sid}/finalize").json()
        return self.c.get(f"/api/verifications/{out['verification_id']}").json()["result"]
