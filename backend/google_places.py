"""Google Places API (New) client: autocomplete, details, nearby, similar-listing search.

SKU notes (India pricing, verify before production):
* Autocomplete with a session token that ends in Place Details is billed per session.
* displayName/formattedAddress/addressComponents/location/types/businessStatus = Pro SKU.
* nationalPhoneNumber/internationalPhoneNumber/rating/userRatingCount = Enterprise SKU.
"""

from __future__ import annotations

import requests

from config import GOOGLE_API_KEY, ApiError

BASE = "https://places.googleapis.com/v1"

DETAIL_FIELDS = ",".join([
    "id", "displayName", "formattedAddress", "shortFormattedAddress", "addressComponents",
    "location", "types", "primaryType", "primaryTypeDisplayName", "businessStatus",
    "googleMapsUri", "nationalPhoneNumber", "internationalPhoneNumber", "websiteUri",
    "rating", "userRatingCount",
])
LIST_FIELDS = ",".join(f"places.{f}" for f in [
    "id", "displayName", "formattedAddress", "shortFormattedAddress", "location",
    "primaryType", "primaryTypeDisplayName", "types", "businessStatus",
])


def _headers(field_mask: str | None = None) -> dict:
    if not GOOGLE_API_KEY:
        raise ApiError("CONFIG_MISSING", "GOOGLE_API_KEY is not configured on the server.", 500)
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": GOOGLE_API_KEY}
    if field_mask:
        headers["X-Goog-FieldMask"] = field_mask
    return headers


def _call(method: str, url: str, field_mask: str | None = None, body: dict | None = None,
          params: dict | None = None) -> dict:
    try:
        resp = requests.request(method, url, headers=_headers(field_mask), json=body,
                                params=params, timeout=15)
    except requests.Timeout:
        raise ApiError("PROVIDER_TIMEOUT", "Google Maps took too long to answer. Try again.", 504)
    except requests.RequestException:
        raise ApiError("PROVIDER_UNAVAILABLE", "Couldn't reach Google Maps. Check the connection.", 502)

    if resp.status_code == 404:
        raise ApiError("PLACE_NOT_FOUND", "That Google listing no longer exists.", 404)
    if resp.status_code in (401, 403):
        raise ApiError("PROVIDER_AUTH", "Google Maps rejected our API key.", 502)
    if resp.status_code == 429:
        raise ApiError("RATE_LIMITED", "Google Maps quota hit. Wait a moment and retry.", 429)
    if resp.status_code == 400:
        raise ApiError("PROVIDER_BAD_REQUEST", "Google Maps couldn't understand that search.", 400)
    if not resp.ok:
        raise ApiError("PROVIDER_UNAVAILABLE", "Google Maps is temporarily unavailable.", 502)
    try:
        return resp.json()
    except ValueError:
        raise ApiError("PROVIDER_UNAVAILABLE", "Google Maps sent an unreadable response.", 502)


def _component(components: list[dict], kind: str) -> str | None:
    for comp in components or []:
        if kind in comp.get("types", []):
            return comp.get("longText")
    return None


def _summary(place: dict) -> dict:
    loc = place.get("location") or {}
    return {
        "place_id": place.get("id"),
        "name": (place.get("displayName") or {}).get("text"),
        "address": place.get("formattedAddress"),
        "short_address": place.get("shortFormattedAddress") or place.get("formattedAddress"),
        "lat": loc.get("latitude"),
        "lng": loc.get("longitude"),
        "primary_type": place.get("primaryType"),
        "type_label": (place.get("primaryTypeDisplayName") or {}).get("text"),
        "types": place.get("types") or [],
        "business_status": place.get("businessStatus"),
    }


# ----------------------------------------------------------------- endpoints
def autocomplete(text: str, session_token: str | None = None, lat: float | None = None,
                 lng: float | None = None, types: list[str] | None = None,
                 addresses: bool = False) -> list[dict]:
    body: dict = {"input": text, "includedRegionCodes": ["in"], "languageCode": "en"}
    if session_token:
        body["sessionToken"] = session_token
    if lat is not None and lng is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 20000.0}}
    if types and not addresses:
        body["includedPrimaryTypes"] = types[:5]
    data = _call("POST", f"{BASE}/places:autocomplete", body=body)
    out = []
    for s in data.get("suggestions", []):
        p = s.get("placePrediction")
        if not p:
            continue
        fmt = p.get("structuredFormat") or {}
        place_types = p.get("types") or []
        if not addresses and "establishment" not in place_types:
            continue
        out.append({
            "place_id": p.get("placeId"),
            "main": (fmt.get("mainText") or {}).get("text") or (p.get("text") or {}).get("text"),
            "secondary": (fmt.get("secondaryText") or {}).get("text"),
            "types": place_types,
        })
    return out


def details(place_id: str, session_token: str | None = None) -> dict:
    params = {"sessionToken": session_token} if session_token else None
    place = _call("GET", f"{BASE}/places/{place_id}", field_mask=DETAIL_FIELDS, params=params)
    comps = place.get("addressComponents") or []
    return {
        **_summary(place),
        "pincode": _component(comps, "postal_code"),
        "state": _component(comps, "administrative_area_level_1"),
        "city": _component(comps, "locality") or _component(comps, "administrative_area_level_3"),
        "phone_national": place.get("nationalPhoneNumber"),
        "phone_international": place.get("internationalPhoneNumber"),
        "website": place.get("websiteUri"),
        "maps_uri": place.get("googleMapsUri"),
        "rating": place.get("rating"),
        "rating_count": place.get("userRatingCount") or 0,
    }


def nearby(lat: float, lng: float, radius_m: float = 150.0, types: list[str] | None = None) -> list[dict]:
    body: dict = {
        "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius_m}},
        "rankPreference": "DISTANCE",
        "maxResultCount": 15,
        "languageCode": "en",
    }
    if types:
        body["includedTypes"] = types
    data = _call("POST", f"{BASE}/places:searchNearby", field_mask=LIST_FIELDS, body=body)
    return [_summary(p) for p in data.get("places", [])]


def text_search(query: str, lat: float | None = None, lng: float | None = None,
                radius_m: float = 3000.0, page_size: int = 10) -> list[dict]:
    body: dict = {"textQuery": query, "pageSize": page_size, "regionCode": "in", "languageCode": "en"}
    if lat is not None and lng is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius_m}}
    data = _call("POST", f"{BASE}/places:searchText", field_mask=LIST_FIELDS, body=body)
    return [_summary(p) for p in data.get("places", [])]


def locate(address: str) -> dict | None:
    """Best-effort coordinates for a free-text address (used for GST principal address)."""
    results = text_search(address, page_size=1)
    return results[0] if results else None
