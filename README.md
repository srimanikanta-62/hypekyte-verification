# HypeKyte Business Verification

A working prototype that answers two separate questions about a business signing up to HypeKyte:

1. **Does the business exist?** Checked against the GST register (gstinapi.in) and Google Maps (Places API, New).
2. **Does the applicant belong to it?** Checked by proving control of a phone number that one of those sources *already* ties to the business.

It returns **VERIFIED / NEEDS REVIEW / UNVERIFIED**, a 0–100 score split into *Business exists* and *Applicant linked*, and a result page
that explains every check, conflict and deduction. The user flow is built to keep typing to a minimum: on-site users can finish
by typing **5 digits**.

![Result page](docs/screenshots/b2_dossier.png)

---

## Run it

**Backend** (Python 3.11+)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # then fill in GOOGLE_API_KEY and GSTIN_API_KEY
uvicorn main:app --port 8000
pytest tests                      # 20 scenario tests, providers mocked, no credits used
```

**Frontend** (Node 20+)

```bash
cd app-builder-studio
npm install
npm run dev                       # http://localhost:8080
```

Set `VITE_API_BASE_URL` if the API isn't on `http://127.0.0.1:8000`.

**Screenshots:** with both servers running, `python docs/capture_screenshots.py` replays the demo scenarios in Edge (Playwright) and
writes `docs/screenshots/`.

| Env var | Meaning |
|---|---|
| `GOOGLE_API_KEY` | Places API (New) key. Restrict it to that API in Google Cloud. |
| `GSTIN_API_KEY` | gstinapi.in key (`x-api-key`) |
| `OTP_MODE=simulated` | OTP "SMS" is shown on the demo phone panel. `live` is the slot for a real SMS provider. |
| `GST_CONTACT_MODE=simulated` | GST-registered mobile for real GSTINs comes from `backend/fixtures/demo_contacts.json`. `live` calls the paid `/contact` endpoint. |

---

## What is live and what is simulated

Every signal in the UI and API carries a provenance tag.

| Piece | Status | Why |
|---|---|---|
| Google Places: autocomplete, details, nearby, text search | **LIVE** | Real API key |
| GST registry lookup (`/v1/gstin/{gstin}`) | **LIVE**, cached 7 days | Free tier: 75 credits; not-found and invalid lookups are free |
| Provider sandbox GSTIN `00AAAAA0000A1ZT` | **SANDBOX** | Free test record. Counted but capped at NEEDS REVIEW, never treated as real evidence |
| GST-registered mobile (`/v1/gstin/{gstin}/contact`) | **SIMULATED** for real GSTINs, **SANDBOX** for the test GSTIN | The endpoint exists but is paid-only |
| SMS delivery of OTP | **SIMULATED** (demo phone panel) | No free SMS route in India: Firebase Phone Auth needs billing, and Indian SMS needs DLT registration |

Code generation, hashing, expiry (2 min), attempt limits (3), resend cooldown (30 s) and send limits are all real. Only the
carrier is replaced.

---

## The flow (user's two-path design, unified)

```
01 Locate    "Are you at the business right now?" → one geolocation tap
02 Identify  tap a nearby business (Nearby Search)  OR  type its name = live Google autocomplete
             → listing card; category is inferred from the listing
03 Registry  GSTIN? yes → paste/type (decoded live, checksum checked, auto-submits at 15 chars)
                         → "Is this your registration?" registry extract → confirm
             no  → rely on the listing (or give an address if not on Maps)
04 Phone     choose the strongest available number: GST-registered mobile (+40) > Google-listed mobile (+30) > own mobile (+5)
             the number is shown masked (98•••••210); the applicant types only the 5 hidden digits
             3 wrong tries → "Verify another way" switches to the next source
05 Code      4-digit OTP arrives on the demo phone; tap it to fill; auto-submits
06 Link      (GST path, optional) link the Google listing, pre-searched from the GST trade name + city
07 Submit    → result page: status, score, checks by source, side-by-side comparison, look-alikes, deductions
```

Keystroke budget: on-site with a listing, **5 digits**. GSTIN path, **one paste plus 5 digits**. Everything else is taps.

UX details: GSTIN decoding (state, PAN, holder type) with no API call · listings matching the typed name sorted first ·
"Not this one" undo · arrow-key autocomplete · auto-advance · resume after refresh (session id in the URL and localStorage) ·
error toasts with action buttons that dismiss after 4 s · landline numbers detected and explained instead of failing · a live
score panel next to the steps · print/copy result.

---

## Verification logic

`backend/scoring.py` keeps the logic in one place and transparent.

**Existence (max 60)**: GST Active **+30** · Google listing operating **+20** · listing with ≥25 reviews **+5** ·
GST↔Google agree on name and PIN (or a registered branch PIN) **+10**

**Association (max 40)**: OTP on GST-registered mobile **+40** · OTP on Google-listed mobile **+30** · OTP on own number **+5** ·
device within 150 m of the business (accuracy ≤200 m) **+10**

**Decision**

| Status | Rule |
|---|---|
| **UNVERIFIED** | Listing permanently closed, **or** no source establishes existence (e.g. an invalid, unregistered or cancelled GSTIN with nothing else) |
| **NEEDS REVIEW** | Any conflict ("cap"), **or** Exists < 20, **or** Belongs < 30 |
| **VERIFIED** | Exists ≥ 20 **and** Belongs ≥ 30 **and** no conflicts: the business exists *and* the applicant controls a number an independent source ties to it |

**Conflicts** (each blocks VERIFIED and deducts points by severity): name entered ≠ GST name (−10) · GST name ≠ listing name
(−15) · GST state ≠ listing state (−15) · GST PIN ≠ listing PIN and not a registered branch (−5) · GSTIN invalid or unregistered
(−10) · GST not Active (−15) · look-alike listings nearby that phone/GST don't resolve (−10) · GSTIN or listing **already verified
on another account** (−20) · ≥3 different GSTINs tried (−10) · claimed on-site but >2 km away (−15) · listing temporarily closed
(−5) · sandbox data (0) · category mismatch (−5, warning only).

**Matching** (`backend/matching.py`)
- Names: compared on *distinctive* tokens. Legal suffixes (Pvt, Ltd, LLP, M/s), generic words (sweets, cafe, store, textiles…)
  and the listing's locality ("Haldiram's – Murthal") are stripped. Score = best of per-token coverage (RapidFuzz) and joined-string
  similarity, against both GST trade and legal name. ≥85 match · 75–85 partial · <75 mismatch.
  Plain fuzzy matching rates "Sharma Sweets" vs "Verma Sweets" at 80%; this scores it 55% (mismatch).
- Address: PIN extracted and compared exactly (and against GST `additional_addresses` branch PINs). State from the GST state code vs
  Google `administrative_area_level_1`.
- Phone: Google formats Indian mobiles 5-5 (`+91 98765 43210`) and landlines by STD code (`+91 8071 890 217`). That grouping is used
  to spot landlines that can't receive SMS.
- Look-alikes: Text Search around the chosen listing; a match is a look-alike if name ≥85 and it shares the PIN or is within 1 km.

**Privacy and security**: full phone numbers, OTP hashes and raw coordinates never leave the server. The client only sees masked
hints, and coordinates are dropped when the case is filed. API keys stay on the backend, which proxies autocomplete.

---

## Scenarios

Covered by `backend/tests/test_scenarios.py` (deterministic, providers mocked) and replayed live in the UI. See
**[docs/scenarios.md](docs/scenarios.md)** for screenshots and reasoning.

| # | Scenario | Result |
|---|---|---|
| 1 | Valid GSTIN, matching name, OTP on GST mobile | VERIFIED |
| 2 | Invalid GSTIN (checksum) / unregistered / cancelled | UNVERIFIED (NEEDS REVIEW if Google evidence exists) |
| 3 | On Google Maps, no GSTIN, OTP on listed mobile | VERIFIED (live: Burfiwala Murthal) |
| 3b | On Maps, listed number is a landline | NEEDS REVIEW |
| 4 | Valid GSTIN but different name / PIN | NEEDS REVIEW |
| 5 | Several similar businesses (Haldiram's ×3 in PIN 131039) | NEEDS REVIEW, unless OTP on that listing's own phone resolves it |
| + | Listing already verified by someone else, claimed on-site but far away, closed listing, phone/OTP attempt limits | covered |

---

## Project layout

```
backend/
  main.py            FastAPI app: session endpoints, error codes, public (masked) session view
  scoring.py         Existence/Association scoring, conflicts, decision, ledger
  matching.py        name/address/phone/distance/category matching
  gstin.py           checksum + decode, gstinapi.in lookup and contact (cached)
  google_places.py   Places API (New): autocomplete, details, nearby, text search
  otp.py             OTP generation/verification + SmsSender interface (simulated sender)
  database.py        SQLite: sessions, provider cache, verifications
  fixtures/          simulated GST contacts (clearly labelled)
  samples/           real captured gstinapi.in responses
  tests/             20 scenario and edge-case tests
app-builder-studio/  React + TanStack Start frontend
  src/routes/verify.tsx     the step-by-step flow
  src/routes/case.$id.tsx   the result page
  src/routes/index.tsx      verification history
  src/components/           VirtualPhone (demo phone), DigitBoxes, GstinField, PlaceSearch, status badge/meters
docs/                 scenarios, screenshots, capture script
research.md           API research and comparison
```

---

## Limitations

- **OTP and GST contact are simulated** on this account (see the table above). In simulated mode anyone can read the code on the
  demo phone, so association is only meaningful once a real SMS sender is plugged in.
- **Knowing a Google-listed number proves little.** It's public. The hidden-digit step is friction against casual misuse; the
  OTP is the actual proof.
- The **GST-registered mobile is often the CA's**, so legitimate owners may fail that step. They fall back to the listing phone.
- Google listings can be created by anyone. The review count is a weak maturity signal, and Places doesn't expose listing age or
  ownership ("claimed") status.
- Geolocation is spoofable and imprecise on desktops. It is a bonus signal only and never decides alone.
- Name matching is token-based with hand-tuned generic-word lists and thresholds. It isn't trained on real fraud data.
- Free GST tier: 75 credits; lookups are cached for 7 days to save them.
- No user accounts or authentication. Sessions are anonymous, and the reviewer queue is the history list.

## If this went into HypeKyte

1. **Real channels**: a DLT-registered SMS/WhatsApp OTP provider (MSG91, Gupshup or 2Factor) plus a paid gstinapi.in plan for `/contact`
   (4–6 credits per call, roughly ₹1.6–4.8 at published pack prices), behind the existing `SmsSender` and `GST_CONTACT_MODE` switches.
2. **Stronger association**: email OTP on the GST-registered email or the website's domain (`websiteUri` from Places) · Google Business
   Profile OAuth (only the real owner can grant access to the listing) · a DigiLocker / PAN name match against the GST legal name for
   proprietorships · a small "verification code" sticker or post for edge cases.
3. **Category-specific registers**: FSSAI licence for restaurants and cafés, and MCA director (DIN) match for companies (see research.md).
4. **Reviewer console**: a NEEDS REVIEW queue with the result page, approve/reject with reasons, and use the decisions to tune thresholds.
5. **Ongoing monitoring**: re-check GST status and listing status monthly (gstinapi.in has vendor monitoring); auto-flag cancelled
   GSTINs or permanently closed listings.
6. **Abuse controls**: rate-limit per IP/device, cap OTP sends per number per day, block disposable numbers, and alert on many
   registrations from one device.
7. **Scale**: replace SQLite with Postgres, sessions with Redis plus a TTL, and queue provider calls with retries and circuit breakers.
