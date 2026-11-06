"""The five assessment scenarios plus fraud / edge cases, end-to-end through the API."""

from conftest import CANCELLED_GSTIN, KAVERI_GSTIN, UNREGISTERED_GSTIN, Flow


def signal(result, sid):
    return next(s for s in result["signals"] if s["id"] == sid)


# ---------------------------------------------------------------- Scenario 1
def test_1_valid_gstin_matching_name_gst_mobile_otp_is_verified(client):
    f = Flow(client, "Kaveri Textiles")
    f.gstin(KAVERI_GSTIN)
    f.confirm()
    f.otp_on("gst", "76543")               # hidden digits of 98•••••210
    r = f.finalize()
    assert r["status"] == "VERIFIED", r["headline"]
    assert r["existence"] == 30 and r["association"] == 40
    assert signal(r, "name_gst")["outcome"] == "pass"


def test_1b_gstin_plus_matching_listing_scores_higher(client):
    f = Flow(client, "Kaveri Textiles")
    f.place("kaveri")
    f.gstin(KAVERI_GSTIN)
    f.confirm()
    f.otp_on("gst", "9876543210")          # full number also accepted
    r = f.finalize()
    assert r["status"] == "VERIFIED"
    # PIN 560011 is not the principal address but IS a registered branch -> cross-match passes
    assert signal(r, "cross")["outcome"] == "pass"
    assert r["score"] >= 95


# ---------------------------------------------------------------- Scenario 2
def test_2_invalid_checksum_gstin_alone_is_unverified(client):
    f = Flow(client, "Kaveri Textiles")
    bad = KAVERI_GSTIN[:-1] + ("A" if KAVERI_GSTIN[-1] != "A" else "B")
    err = f.gstin(bad, expect=422)
    assert err["code"] == "GSTIN_INVALID_CHECKSUM"
    r = f.finalize()
    assert r["status"] == "UNVERIFIED"
    assert signal(r, "gst")["outcome"] == "fail"


def test_2b_unregistered_gstin_is_unverified(client):
    f = Flow(client, "Zed Traders")
    assert f.gstin(UNREGISTERED_GSTIN, expect=404)["code"] == "GSTIN_NOT_FOUND"
    assert f.finalize()["status"] == "UNVERIFIED"


def test_2c_invalid_gstin_then_google_path_is_capped_at_review(client):
    f = Flow(client, "Brew & Bloom Cafe")
    f.gstin(UNREGISTERED_GSTIN, expect=404)
    f.place("brew")
    f.otp_on("places", "23456")
    r = f.finalize()
    assert r["status"] == "NEEDS_REVIEW"
    assert any("not registered" in c for c in r["caps"])


def test_2d_cancelled_gstin_is_unverified(client):
    f = Flow(client, "Sharma Sweets")
    assert f.gstin(CANCELLED_GSTIN, expect=409)["code"] == "GSTIN_INACTIVE"
    f.confirm()
    assert f.finalize()["status"] == "UNVERIFIED"


# ---------------------------------------------------------------- Scenario 3
def test_3_on_maps_without_gstin_listing_mobile_otp_is_verified(client):
    f = Flow(client)                      # picked from list: no name typed at all
    f.place("brew", source="nearby")
    f.otp_on("places", "23456")           # 91•••••789 -> hidden 23456
    r = f.finalize()
    assert r["status"] == "VERIFIED", r["headline"]
    assert r["existence"] == 25 and r["association"] == 30


def test_3b_listing_with_landline_cannot_link_applicant(client):
    f = Flow(client, "Annapurna Bhojnalaya")
    f.place("landline")
    err = f.post("/phone/target", {"source": "places"}, expect=422)
    assert err["code"] == "PHONE_NOT_SMS_CAPABLE"
    f.otp_on("self", "9000000001")
    r = f.finalize()
    assert r["status"] == "NEEDS_REVIEW"
    assert r["association"] == 5
    assert signal(r, "landline")["outcome"] == "info"


# ---------------------------------------------------------------- Scenario 4
def test_4_valid_gstin_but_different_name_needs_review(client):
    f = Flow(client, "Sunrise Electronics")
    f.gstin(KAVERI_GSTIN)
    f.confirm()
    f.otp_on("gst", "76543")
    r = f.finalize()
    assert r["status"] == "NEEDS_REVIEW"
    assert signal(r, "name_gst")["outcome"] == "fail"


def test_4b_valid_gstin_but_listing_in_unregistered_pin_needs_review(client):
    f = Flow(client, "Kaveri Textiles")
    f.place("kaveri_far")
    f.gstin(KAVERI_GSTIN)
    f.confirm()
    f.otp_on("gst", "76543")
    r = f.finalize()
    assert r["status"] == "NEEDS_REVIEW"
    assert signal(r, "cross")["outcome"] == "warn"
    assert any("PIN" in c for c in r["caps"])


# ---------------------------------------------------------------- Scenario 5
def test_5_similar_businesses_same_pin_need_review_without_phone_proof(client):
    f = Flow(client, "Gupta Sweets")
    s = f.place("sweets_a")["session"]
    assert any(x["is_lookalike"] for x in s["similar"])
    f.otp_on("self", "9000000002")
    r = f.finalize()
    assert r["status"] == "NEEDS_REVIEW"
    assert signal(r, "lookalikes")["outcome"] == "warn"


def test_5b_listing_phone_otp_resolves_the_ambiguity(client):
    f = Flow(client, "Gupta Sweets")
    f.place("sweets_a")
    f.otp_on("places", "14000")            # 93•••••001
    r = f.finalize()
    assert r["status"] == "VERIFIED"
    assert signal(r, "lookalikes")["outcome"] == "pass"


# ---------------------------------------------------------------- Edge / fraud
def test_permanently_closed_listing_is_unverified(client):
    f = Flow(client, "Old Town Electronics")
    f.place("closed")
    f.otp_on("places", "30000")
    assert f.finalize()["status"] == "UNVERIFIED"


def test_wrong_phone_three_times_locks_that_source(client):
    f = Flow(client, "Kaveri Textiles")
    f.gstin(KAVERI_GSTIN)
    f.confirm()
    f.post("/phone/target", {"source": "gst"})
    assert f.post("/phone/claim", {"digits": "11111"}, 409)["attempts_left"] == 2
    assert f.post("/phone/claim", {"digits": "22222"}, 409)["attempts_left"] == 1
    assert f.post("/phone/claim", {"digits": "33333"}, 429)["code"] == "PHONE_ATTEMPTS_EXCEEDED"
    targets = client.get(f"/api/sessions/{f.sid}").json()["session"]["phone_targets"]
    assert next(t for t in targets if t["source"] == "gst")["exhausted"] is True


def test_wrong_otp_is_rejected_and_counted(client):
    f = Flow(client)
    f.place("brew")
    f.post("/phone/target", {"source": "places"})
    f.post("/phone/claim", {"digits": "23456"})
    inbox = client.get(f"/api/dev/sms/{f.sid}").json()["messages"]
    wrong = "0000" if inbox[-1]["body"][:4] != "0000" else "1111"
    assert f.post("/otp/verify", {"code": wrong}, 422)["attempts_left"] == 2


def test_duplicate_claim_of_verified_listing_needs_review(client):
    first = Flow(client)
    first.place("brew")
    first.otp_on("places", "23456")
    assert first.finalize()["status"] == "VERIFIED"

    second = Flow(client)
    second.place("brew")
    second.otp_on("places", "23456")
    r = second.finalize()
    assert r["status"] == "NEEDS_REVIEW"
    assert any("already verified" in c for c in r["caps"])


def test_claiming_to_be_on_site_but_far_away_needs_review(client):
    f = Flow(client)
    f.post("/presence", {"at_business": True, "lat": 28.61, "lng": 77.20, "accuracy": 20})  # Delhi
    f.place("brew")                                                                        # Mumbai
    f.otp_on("places", "23456")
    r = f.finalize()
    assert r["status"] == "NEEDS_REVIEW"
    assert signal(r, "presence")["outcome"] == "fail"


def test_on_site_presence_adds_points_and_lists_nearby(client):
    f = Flow(client, "Brew Bloom")
    out = f.post("/presence", {"at_business": True, "lat": 19.0597, "lng": 72.8296, "accuracy": 15})
    assert out["nearby"][0]["place_id"] == "brew" and out["nearby"][0]["name_match"]
    f.place("brew", source="nearby")
    f.otp_on("places", "23456")
    r = f.finalize()
    assert signal(r, "presence")["points"] == 10
    assert r["status"] == "VERIFIED"


def test_category_mismatch_is_penalised_but_not_blocking(client):
    f = Flow(client)
    f.post("/profile", {"category": "Hotel"})
    f.place("brew")
    f.otp_on("places", "23456")
    r = f.finalize()
    assert signal(r, "category")["points"] == -5
    assert r["status"] == "VERIFIED"


def test_session_never_exposes_full_phone_numbers(client):
    f = Flow(client, "Kaveri Textiles")
    f.place("kaveri")
    f.gstin(KAVERI_GSTIN)
    view = f.confirm()["session"]
    blob = str(view)
    assert "9876543210" not in blob and "98765 43210" not in blob
