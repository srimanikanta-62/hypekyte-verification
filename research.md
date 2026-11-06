# Research summary: verifying Indian businesses

**Question:** which data sources can show that (a) a business exists and (b) the person registering it is associated with it, and
which of them are practical for a prototype?

**Decision:** **gstinapi.in** (GST register) and **Google Places API (New)** as the two data sources, joined by **phone-control OTP**
on a number one of those sources attributes to the business. Everything below marked ✅ was called live during this project.
Marked ◻ means from public documentation only.

---

## 1. Comparison

| Method | API? | Cost / sandbox | What it returns | Proves existence? | Proves association? | Integration | Used |
|---|---|---|---|---|---|---|---|
| **GSTIN, gstinapi.in** ✅ | REST, `x-api-key` | 75 free credits; packs ₹199/250 → ₹2,499/6,250 (₹0.80–0.40 per lookup); failed and not-found calls free; sandbox GSTIN free | legal and trade name, status, registration/cancellation date, taxpayer type, address + PIN + state code, nature of business, branches (`include=profile`) | **Yes**: government register | No (by itself) | Easy | **Yes** |
| **GST contact, gstinapi.in `/contact`** ✅ (sandbox) | REST | **Paid accounts only**, 4–6 credits, charged even if empty | mobile + email filed with the GST registration | — | **Yes, strongest available**: OTP on the GST-filed mobile | Easy | **Simulated** (free tier) |
| **Google Places API (New)** ✅ | REST, `X-Goog-Api-Key` + field mask | Billing account needed; India free caps per SKU/month: Text Search Pro 35k, Enterprise 7k; Essentials IDs unlimited | name, address components (PIN, state), location, types, business status, phone, website, rating, review count, Maps link | **Supporting**: public, operating presence | Only via its **published phone** + OTP | Easy | **Yes** |
| Places Autocomplete (New) ✅ | REST | Per session (autocomplete + one Details call) | establishment predictions | — | — | Easy | **Yes** (search box) |
| Places Nearby Search (New) ✅ | REST | Pro/Enterprise SKU | businesses around a coordinate | — | On-site presence (weak, spoofable) | Easy | **Yes** (on-site picker) |
| GSTIN offline checksum ✅ | none | free | structural validity, state, PAN, holder type | No | No | Trivial | **Yes** |
| FSSAI licence ◻ | No official public API. FoSCoS portal search is manual/captcha. Third-party KYC APIs (e.g. Surepass, Signzy, IDfy, Gridlines) are paid and need sales onboarding | licence no., FBO name, premises address, validity, category | **Yes** for food businesses | No | Medium (vendor onboarding) | Future |
| MCA (CIN/LLPIN) ◻ | No free official API; MCA21 master data via portal. Third-party APIs paid | company status, incorporation date, registered office, **directors (DIN)** | **Yes** for companies/LLPs | Partially: director name vs applicant | Medium | Future |
| Udyam (MSME) ◻ | Official verification is portal-based with OTP to the registrant; third-party APIs paid | enterprise name, type, address, activity | Yes | Partially (OTP to registrant) | Medium–hard | Future |
| Phone OTP, SMS ◻ | Firebase Phone Auth needs the **Blaze (billing) plan** (since 2024), and test numbers need billing too. Indian SMS needs **DLT** template registration. 2Factor ≈ ₹0.12–0.15/SMS, Fast2SMS ≈ ₹0.11–0.25/SMS (+18% GST) | control of a number | No | **Yes, if the number is on record** | Easy code, slow DLT paperwork | **Simulated** sender |
| Email OTP, Resend ◻ | Free: 3,000/month, 100/day; needs a verified domain | control of a mailbox | No | Yes if it's the GST-filed email or on the website's domain | Easy | Future |
| Google Business Profile OAuth ◻ | OAuth, requires Google approval | which listings the Google account manages | — | **Yes, strong**: only the owner can grant it | Hard (app review) | Future |

### Providers considered for GST

| Provider | Notes | Outcome |
|---|---|---|
| **gstinapi.in** | Working key, free credits, free sandbox GSTIN, clear error codes (400/401/402/403/404/429/502), 60 req/min, Python SDK, and the only one with a GST **contact** endpoint | **Chosen** |
| APIserver.in | Sandbox playground looked good (₹0.19 + GST per success, failures free), but API-key access was never granted | Dropped. Its old sample responses were replaced with real gstinapi.in captures |
| GSTVerify | ₹299/month for 100 calls; developer access on the free plan unclear | Not pursued |
| FinAGG `SEARCHGSTIN` | ≈₹0.05/call advertised; sandbox terms unclear | Not pursued |

---

## 2. What each source can and cannot prove

| Evidence | Establishes | Does **not** establish |
|---|---|---|
| GST record Active | The legal entity exists and is tax-registered at an address | That the applicant works there |
| Google listing operating, reviewed | A public, customer-facing presence at a location | Ownership. Anyone can create or suggest a listing |
| Names/PIN agree across GST and Google | Two independent sources describe the same business | Association |
| OTP on the **GST-filed** mobile | The applicant controls the contact the business gave the government | Legal authority (it may be the CA's phone) |
| OTP on the **Google-listed** mobile | The applicant controls the business's public phone | Much, if the number is shared by staff |
| OTP on the applicant's own number | The applicant is reachable | Anything about the business |
| Device on-site | The applicant was physically there | Ownership; GPS is spoofable |

Conclusion: no single API proves association. The design leans on **"control a channel that an independent source already
attributes to the business"**, and sends everything that can't reach that bar to human review instead of auto-rejecting it.

---

## 3. Live findings from this project

**gstinapi.in**
- `GET /v1/gstin/{gstin}?include=profile` returns `success, test, data{legal_name, trade_name, status, taxpayer_type, registration_date,
  cancellation_date, state_code, address, city, pincode, address_details{…}, nature_of_business, block_status, additional_addresses}`,
  plus `credits_remaining`. Captured in `backend/samples/gstinapi_lookup_sandbox.json`.
- `/contact` on the sandbox returns `data.mobile` and `data.email` with `contact_found: true`, `credits_charged: 0`
  (`samples/gstinapi_contact_sandbox.json`).
- A not-found GSTIN returns HTTP 404 `{"error": "GSTIN not found in GST database"}` and isn't charged. Bad format returns HTTP 400 with a
  `fix` hint. Both captured.
- The demo account had **10 credits** left, so lookups are cached in SQLite for 7 days.

**Google Places (New)**
- Autocomplete "Haldiram Murthal" returns the establishment directly. Details give PIN `131039`, state `Haryana`, 4,654 reviews,
  `businessStatus: OPERATIONAL`.
- The phone came back as `+91 8071 890 217`, which looks like a mobile (starts with 8) but is a Bangalore `080` landline. Google
  formats real mobiles as `+91 98765 43210` (5-5), and that grouping is how the app detects landlines.
- Text Search "Haldiram" near Murthal: **3 listings in PIN 131039**. This is a ready-made live example of scenario 5.
- Nearby Search at 200 m: the listing is the 4th closest place, behind a hotel, a GST office and an EV charger. That's why the
  picker sorts name matches first.

---

## 4. Proposed production workflow

1. Applicant opens a case; optionally shares location once (Nearby Search picker; distance kept, coordinates dropped).
2. Picks the Google listing (autocomplete) or says it's not on Maps.
3. Optional GSTIN: checksum offline, then register lookup (cached), then confirm the registry extract.
4. Phone: the strongest on-record number (GST `/contact` > Google listing > own), shown masked. The applicant types the hidden digits,
   then an OTP via a DLT-registered SMS/WhatsApp provider.
5. Scoring (Exists / Belongs / conflicts) gives VERIFIED / NEEDS REVIEW / UNVERIFIED with a dossier.
6. NEEDS REVIEW goes to an ops queue (documents: GST certificate, FSSAI licence, utility bill, Google Business Profile access).
7. Monthly re-checks of GST status and listing status; flag cancellations and closures.

## 5. References

- gstinapi.in: https://www.gstinapi.in/ · docs https://www.gstinapi.in/docs · OpenAPI https://www.gstinapi.in/openapi.json · https://www.gstinapi.in/llms.txt
- Places API (New) Text Search: https://developers.google.com/maps/documentation/places/web-service/text-search
- Place data fields and SKUs: https://developers.google.com/maps/documentation/places/web-service/data-fields
- Autocomplete (New): https://developers.google.com/maps/documentation/places/web-service/place-autocomplete
- Place types: https://developers.google.com/maps/documentation/places/web-service/place-types
- Google Maps Platform India pricing FAQ: https://developers.google.com/maps/billing-and-pricing/india
- Firebase Auth pricing and Blaze requirement: https://firebase.google.com/pricing
- 2Factor: https://www.2factor.in/ · Fast2SMS: https://www.fast2sms.com/ · Resend: https://resend.com/
- APIserver.in: https://apiserver.in/
