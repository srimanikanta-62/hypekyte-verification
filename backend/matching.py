"""Text, address, phone and distance matching helpers.

Design notes
------------
* Business names are compared on their *distinctive* tokens only. Generic words
  ("sweets", "cafe", "store"), legal suffixes ("pvt", "ltd") and branch
  localities ("Haldiram's - Murthal") are stripped first, otherwise two
  different businesses such as "Sharma Sweets" and "Verma Sweets" look ~80%
  similar purely because they share the word "sweets".
* Phone numbers: Google formats Indian mobiles as "+91 98765 43210" (5-5) and
  landlines with an STD-code grouping ("+91 80 7189 0217", "+91 8071 890 217").
  The grouping is the most reliable mobile/landline signal available without
  another API, because many landline numbers also start with 6-9.
"""

from __future__ import annotations

import math
import re

from rapidfuzz import fuzz

LEGAL_WORDS = {
    "pvt", "private", "ltd", "limited", "llp", "opc", "inc", "co", "company",
    "corp", "corporation", "m", "s", "ms", "prop", "proprietor", "the", "and",
    "of", "firm",
}

GENERIC_WORDS = {
    # food & drink
    "restaurant", "restaurants", "cafe", "coffee", "roasters", "bakery", "bakers",
    "sweets", "sweet", "dhaba", "kitchen", "foods", "food", "snacks", "eatery",
    "bar", "grill", "family", "veg", "pure", "vegetarian", "dining", "bistro",
    "canteen", "juice", "tea", "chai", "pizza", "biryani",
    # retail
    "shop", "store", "stores", "mart", "supermarket", "retail", "traders",
    "trading", "textiles", "textile", "garments", "fashion", "fashions",
    "boutique", "collection", "emporium", "bazaar", "general", "provision",
    "provisions", "electronics", "mobiles", "jewellers", "jewellery",
    # hospitality / events
    "hotel", "hotels", "resort", "inn", "lodge", "events", "event", "management",
    "organisers", "organizers", "planners", "caterers", "catering", "banquet",
    "banquets", "hall", "venue", "weddings", "wedding",
    # business boilerplate
    "enterprises", "enterprise", "services", "service", "solutions", "group",
    "house", "center", "centre", "corner", "point", "outlet", "branch",
    "india", "indian", "international", "industries", "agency", "agencies",
}

NAME_MATCH = 85     # >= : names refer to the same business
NAME_PARTIAL = 75   # >= : plausible (e.g. brand vs legal name); below = mismatch


# --------------------------------------------------------------------------- text
def normalize(value: str | None) -> str:
    text = str(value or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"'s\b", "", text)          # haldiram's -> haldiram
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def _tokens(value: str | None, extra_stop: set[str] | None = None) -> list[str]:
    stop = LEGAL_WORDS | GENERIC_WORDS | (extra_stop or set())
    return [t for t in normalize(value).split() if t not in stop and len(t) > 1]


def _token_coverage(small: list[str], large: list[str]) -> float:
    """Average best per-token similarity of the smaller set inside the larger one."""
    if not small or not large:
        return 0.0
    total = 0.0
    for token in small:
        best = max(fuzz.ratio(token, other) for other in large)
        total += best if best >= 88 else best * 0.5   # weak token matches count half
    return total / len(small)


def name_similarity(a: str | None, b: str | None, extra_stop: set[str] | None = None) -> float | None:
    """0-100 similarity of two business names; None if either side is empty."""
    if not normalize(a) or not normalize(b):
        return None

    ta, tb = _tokens(a, extra_stop), _tokens(b, extra_stop)
    if not ta or not tb:
        # Name made only of generic words ("The Coffee House") - compare whole strings.
        return round(fuzz.token_set_ratio(normalize(a), normalize(b)), 1)

    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    coverage = _token_coverage(small, large)
    joined = fuzz.ratio("".join(ta), "".join(tb))   # "haldi rams" vs "haldirams"
    return round(max(coverage, joined), 1)


def name_verdict(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= NAME_MATCH:
        return "match"
    if score >= NAME_PARTIAL:
        return "partial"
    return "mismatch"


def listing_name_variants(name: str | None) -> list[str]:
    """Google often names branches 'Brand - Locality'; compare both forms."""
    if not name:
        return []
    variants = [name]
    for sep in (" - ", " – ", " | ", ", "):
        if sep in name:
            variants.append(name.split(sep)[0])
    return variants


def best_name_similarity(submitted: str | None, candidates: list[str | None],
                         extra_stop: set[str] | None = None) -> tuple[float | None, str | None]:
    best, best_name = None, None
    for candidate in candidates:
        for variant in listing_name_variants(candidate):
            score = name_similarity(submitted, variant, extra_stop)
            if score is not None and (best is None or score > best):
                best, best_name = score, candidate
    return best, best_name


def matched_words(submitted: str | None, target: str | None) -> list[str]:
    """Words of `target` that also occur (fuzzily) in `submitted` - used for UI highlighting."""
    sub = normalize(submitted).split()
    out = []
    for word in str(target or "").split():
        w = normalize(word)
        if w and any(fuzz.ratio(w, s) >= 88 for s in sub):
            out.append(word)
    return out


# ------------------------------------------------------------------------ address
PIN_RE = re.compile(r"(?<!\d)([1-9]\d{5})(?!\d)")


def extract_pincode(text: str | None) -> str | None:
    match = PIN_RE.search(str(text or ""))
    return match.group(1) if match else None


GST_STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "25": "Daman and Diu", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "28": "Andhra Pradesh (old)", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}


def state_name_for_code(code: str | None) -> str | None:
    return GST_STATE_CODES.get(str(code or "").zfill(2)) if code else None


def same_state(gst_state_code: str | None, place_state: str | None) -> bool | None:
    expected = state_name_for_code(gst_state_code)
    if not expected or not place_state:
        return None
    a, b = normalize(expected), normalize(place_state)
    if a == b or a in b or b in a:
        return True
    # "Delhi" vs "National Capital Territory of Delhi", "Orissa" vs "Odisha"
    return fuzz.token_set_ratio(a, b) >= 85


def address_similarity(a: str | None, b: str | None) -> float | None:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return None
    return round(fuzz.token_set_ratio(na, nb), 1)


# -------------------------------------------------------------------------- phone
def phone_digits(value: str | None) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    return digits


def is_indian_mobile(number: str | None, formatted: str | None = None) -> bool:
    """True only for numbers that can receive SMS (Indian mobile series)."""
    digits = phone_digits(number)
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        return False
    if formatted:
        # Google/libphonenumber formatting: mobiles are grouped 5-5.
        tail = re.sub(r"^\+?91[\s-]*", "", formatted.strip()).lstrip("0").strip()
        groups = [g for g in re.split(r"[\s-]+", tail) if g]
        if len(groups) > 1 and [len(g) for g in groups] != [5, 5]:
            return False
    return True


HIDDEN_START, HIDDEN_END = 2, 7   # hide digits 3..7 -> "98•••••210"


def phone_hint(number: str | None) -> dict | None:
    digits = phone_digits(number)
    if len(digits) != 10:
        return None
    return {
        "prefix": digits[:HIDDEN_START],
        "suffix": digits[HIDDEN_END:],
        "hidden": HIDDEN_END - HIDDEN_START,
        "masked": f"{digits[:HIDDEN_START]}{'•' * (HIDDEN_END - HIDDEN_START)}{digits[HIDDEN_END:]}",
    }


def mask_phone(number: str | None) -> str | None:
    hint = phone_hint(number)
    return hint["masked"] if hint else None


def claim_matches(on_record: str | None, typed: str) -> bool:
    """User may type only the hidden digits or the full 10-digit number."""
    digits = phone_digits(on_record)
    typed_digits = re.sub(r"\D", "", typed or "")
    if len(digits) != 10:
        return False
    if len(typed_digits) == HIDDEN_END - HIDDEN_START:
        return digits[HIDDEN_START:HIDDEN_END] == typed_digits
    return phone_digits(typed_digits) == digits


# ----------------------------------------------------------------------- distance
def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ----------------------------------------------------------------------- category
CATEGORIES = ["Restaurant", "Café", "Retail Store", "Event Organizer", "Hotel", "Other"]

CATEGORY_TYPES = {
    "Café": {"cafe", "coffee_shop", "coffee_stand", "coffee_roastery", "tea_house",
             "bakery", "cake_shop", "pastry_shop", "dessert_shop", "juice_shop",
             "ice_cream_shop", "donut_shop", "cafeteria"},
    "Restaurant": {"restaurant", "fast_food_restaurant", "fine_dining_restaurant",
                   "family_restaurant", "indian_restaurant", "north_indian_restaurant",
                   "south_indian_restaurant", "vegetarian_restaurant", "food_court",
                   "meal_takeaway", "meal_delivery", "bar", "pub", "diner",
                   "breakfast_restaurant", "brunch_restaurant", "pizza_restaurant",
                   "chinese_restaurant", "barbecue_restaurant", "sandwich_shop",
                   "dessert_restaurant", "buffet_restaurant"},
    "Hotel": {"hotel", "lodging", "resort_hotel", "motel", "hostel", "inn",
              "guest_house", "bed_and_breakfast", "extended_stay_hotel"},
    "Event Organizer": {"event_venue", "banquet_hall", "wedding_venue", "convention_center",
                        "concert_hall", "auditorium", "community_center", "live_music_venue",
                        "night_club", "catering_service", "event_planner"},
    "Retail Store": {"store", "clothing_store", "grocery_store", "supermarket",
                     "convenience_store", "electronics_store", "department_store",
                     "shoe_store", "jewelry_store", "book_store", "gift_shop",
                     "furniture_store", "home_goods_store", "hardware_store",
                     "shopping_mall", "market", "food_store", "candy_store",
                     "confectionery", "cell_phone_store", "sporting_goods_store",
                     "pet_store", "liquor_store", "cosmetics_store", "womens_clothing_store",
                     "discount_store", "general_store", "wholesaler", "toy_store"},
}

AUTOCOMPLETE_TYPES = {   # max 5 per Autocomplete request
    "Restaurant": ["restaurant", "food_court", "bar", "meal_takeaway", "cafe"],
    "Café": ["cafe", "coffee_shop", "bakery", "tea_house", "dessert_shop"],
    "Retail Store": ["store", "clothing_store", "grocery_store", "supermarket", "electronics_store"],
    "Event Organizer": ["event_venue", "banquet_hall", "wedding_venue", "convention_center", "catering_service"],
    "Hotel": ["hotel", "lodging", "resort_hotel", "guest_house", "hostel"],
}


def infer_category(primary_type: str | None, types: list[str] | None) -> str | None:
    if primary_type:
        for category, known in CATEGORY_TYPES.items():
            if primary_type in known:
                return category
    for t in types or []:
        for category, known in CATEGORY_TYPES.items():
            if t in known:
                return category
    return None


def category_consistent(category: str | None, types: list[str] | None) -> bool | None:
    if not category or category == "Other" or not types:
        return None
    known = CATEGORY_TYPES.get(category, set())
    if category == "Event Organizer":
        return None   # Google has no organiser type: never penalise
    return bool(known & set(types))
