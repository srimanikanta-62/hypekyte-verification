"""GSTIN validation, offline decoding and gstinapi.in registry / contact lookups.

What each piece proves
* Format + checksum (offline): the string *could* be a GSTIN. Proves nothing about registration.
* Registry lookup (GET /v1/gstin/{gstin}): the GSTIN is registered, its status, legal/trade
  name and principal address. Proves the business exists on the GST register - not that the
  applicant is associated with it.
* Contact lookup (GET /v1/gstin/{gstin}/contact): mobile/email filed with the GST
  registration. An OTP on this number is the strongest applicant-association signal we have.
  Paid accounts only, so it is simulated from fixtures unless GST_CONTACT_MODE=live
  (the provider's sandbox GSTIN always returns a free live sample).
"""

from __future__ import annotations

import json
import re

import requests

import database
from config import (FIXTURES_DIR, GST_CONTACT_MODE, GSTIN_API_KEY, SANDBOX_GSTIN, ApiError)
from matching import state_name_for_code

API_BASE = "https://www.gstinapi.in/v1/gstin"
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LOOKUP_CACHE_S = 7 * 24 * 3600      # registry data changes rarely; credits are scarce
CONTACT_CACHE_S = 30 * 24 * 3600

PAN_HOLDER_TYPES = {
    "C": "Company", "P": "Individual / Proprietor", "H": "Hindu Undivided Family",
    "F": "Firm / LLP", "A": "Association of Persons", "T": "Trust", "B": "Body of Individuals",
    "L": "Local Authority", "J": "Artificial Juridical Person", "G": "Government",
}


def clean(value: str | None) -> str:
    return re.sub(r"[\s\-./]", "", str(value or "")).upper()


def checksum_char(gstin: str) -> str:
    total, factor = 0, 2
    for ch in reversed(gstin[:14]):
        product = BASE36.index(ch) * factor
        total += product // 36 + product % 36
        factor = 1 if factor == 2 else 2
    return BASE36[(36 - total % 36) % 36]


def validate(gstin: str) -> str:
    """Return 'VALID', 'INVALID_FORMAT' or 'INVALID_CHECKSUM' (no network)."""
    if not GSTIN_PATTERN.fullmatch(gstin):
        return "INVALID_FORMAT"
    if gstin != SANDBOX_GSTIN and gstin[-1] != checksum_char(gstin):
        return "INVALID_CHECKSUM"
    return "VALID"


def decode(gstin: str) -> dict:
    """Everything a GSTIN reveals by itself - shown to the user instantly, zero API calls."""
    g = clean(gstin)
    pan = g[2:12] if len(g) >= 12 else None
    return {
        "state_code": g[:2] if len(g) >= 2 else None,
        "state": state_name_for_code(g[:2]) if len(g) >= 2 else None,
        "pan": pan,
        "holder_type": PAN_HOLDER_TYPES.get(pan[3]) if pan and len(pan) >= 4 else None,
        "registration_number": g[12] if len(g) >= 13 else None,
    }


# ------------------------------------------------------------------- registry
def _headers() -> dict:
    if not GSTIN_API_KEY:
        raise ApiError("CONFIG_MISSING", "GSTIN_API_KEY is not configured on the server.", 500)
    return {"x-api-key": GSTIN_API_KEY}


def _request(url: str) -> requests.Response:
    try:
        return requests.get(url, headers=_headers(), timeout=20)
    except requests.Timeout:
        raise ApiError("PROVIDER_TIMEOUT", "The GST registry took too long to answer. Try again.", 504)
    except requests.RequestException:
        raise ApiError("PROVIDER_UNAVAILABLE", "Couldn't reach the GST registry. Try again shortly.", 502)


def _raise_for_status(resp: requests.Response) -> None:
    if resp.status_code == 404:
        raise ApiError("GSTIN_NOT_FOUND", "This GSTIN isn't on the GST register.", 404)
    if resp.status_code == 400:
        raise ApiError("GSTIN_INVALID_FORMAT", "The GST registry rejected this GSTIN's format.", 400)
    if resp.status_code in (401, 403):
        raise ApiError("PROVIDER_AUTH", "The GST registry rejected our API credentials.", 502)
    if resp.status_code == 402:
        raise ApiError("PROVIDER_CREDITS", "GST lookup credits are exhausted on this demo account.", 502)
    if resp.status_code == 429:
        raise ApiError("RATE_LIMITED", "Too many GST lookups right now. Wait a moment and retry.", 429)
    if not resp.ok:
        raise ApiError("PROVIDER_UNAVAILABLE", "The GST registry is temporarily unavailable.", 502)


def lookup(gstin: str) -> dict:
    """Registry record (cached). Raises ApiError for invalid / unregistered / provider failures."""
    g = clean(gstin)
    status = validate(g)
    if status == "INVALID_FORMAT":
        raise ApiError("GSTIN_INVALID_FORMAT", "A GSTIN has 15 characters, like 29ABCDE1234F1Z5.", 422)
    if status == "INVALID_CHECKSUM":
        raise ApiError("GSTIN_INVALID_CHECKSUM",
                       "The last character doesn't check out. One of the characters is mistyped.", 422)

    cached = database.cache_get(f"gst:{g}", LOOKUP_CACHE_S)
    if cached:
        return {**cached, "cached": True}

    resp = _request(f"{API_BASE}/{g}?include=profile")
    _raise_for_status(resp)
    try:
        payload = resp.json()
    except ValueError:
        raise ApiError("PROVIDER_UNAVAILABLE", "The GST registry sent an unreadable response.", 502)
    if not payload.get("success"):
        raise ApiError("GSTIN_NOT_FOUND", payload.get("error") or "No GST record found.", 404)

    data = payload.get("data") or {}
    details = data.get("address_details") or {}
    record = {
        "gstin": data.get("gstin") or g,
        "legal_name": data.get("legal_name"),
        "trade_name": data.get("trade_name"),
        "status": data.get("status") or "Unknown",
        "taxpayer_type": data.get("taxpayer_type"),
        "constitution": data.get("business_constitution"),
        "registration_date": data.get("registration_date"),
        "cancellation_date": data.get("cancellation_date"),
        "state_code": data.get("state_code") or g[:2],
        "state": state_name_for_code(data.get("state_code") or g[:2]) or details.get("state"),
        "address": data.get("address"),
        "city": data.get("city") or details.get("city") or details.get("district"),
        "pincode": data.get("pincode") or details.get("pincode"),
        "nature_of_business": data.get("nature_of_business") or [],
        "block_status": data.get("block_status"),
        "additional_addresses": data.get("additional_addresses") or [],
        "test": bool(payload.get("test")),
        "mode": "sandbox" if payload.get("test") else "live",
    }
    database.cache_put(f"gst:{g}", record)
    return {**record, "cached": False}


def is_active(record: dict) -> bool:
    return str(record.get("status", "")).strip().lower() == "active"


# -------------------------------------------------------------------- contact
def _fixture_contacts() -> dict:
    path = FIXTURES_DIR / "demo_contacts.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("contacts", {})
    except (OSError, ValueError):
        return {}


def contact(gstin: str) -> dict:
    """GST-registered mobile. Returns {found, mobile, mode, note}; never raises for 'not found'."""
    g = clean(gstin)
    use_live = g == SANDBOX_GSTIN or GST_CONTACT_MODE == "live"

    if not use_live:
        entry = _fixture_contacts().get(g)
        if entry and entry.get("mobile"):
            return {"found": True, "mobile": entry["mobile"], "mode": "simulated",
                    "note": "Simulated GST contact (the paid /contact endpoint is not enabled on this demo account)."}
        return {"found": False, "mobile": None, "mode": "simulated",
                "note": "No GST-registered mobile available on the free tier for this GSTIN."}

    cached = database.cache_get(f"gst-contact:{g}", CONTACT_CACHE_S)
    if cached:
        return cached

    resp = _request(f"{API_BASE}/{g}/contact")
    if resp.status_code == 403:
        return {"found": False, "mobile": None, "mode": "live",
                "note": "GST contact lookup needs a paid gstinapi.in account."}
    if resp.status_code == 404:
        return {"found": False, "mobile": None, "mode": "live", "note": "No contact on record."}
    _raise_for_status(resp)
    payload = resp.json()
    data = payload.get("data") or {}
    result = {
        "found": bool(payload.get("contact_found") and data.get("mobile")),
        "mobile": data.get("mobile"),
        "mode": "sandbox" if payload.get("test") else "live",
        "note": payload.get("note"),
    }
    database.cache_put(f"gst-contact:{g}", result)
    return result
