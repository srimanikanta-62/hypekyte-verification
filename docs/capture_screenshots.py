"""Drive the running app through the demo scenarios and save screenshots.

Prereqs: backend on :8000, frontend on :8080, `pip install playwright`, and Microsoft Edge
(or run `playwright install chromium` and drop channel="msedge").

    python docs/capture_screenshots.py

Uses live Google Places + gstinapi.in calls (sandbox / not-found lookups cost no GST credits).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

URL = "http://localhost:8080"
OUT = Path(__file__).resolve().parent / "screenshots"
HALDIRAM = {"latitude": 29.04845, "longitude": 77.0665, "accuracy": 20}


def shot(page: Page, name: str, full: bool = False) -> None:
    time.sleep(0.7)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print("  saved", name)


def remote_start(page: Page) -> None:
    page.goto(f"{URL}/verify")
    page.wait_for_selector("text=Are you at the business")
    page.click("text=No, I'm somewhere else")
    page.wait_for_selector("text=Find your business")


def search_and_pick(page: Page, query: str) -> None:
    page.fill("input[role=combobox]", query)
    page.wait_for_selector("#place-listbox li[role=option] button", timeout=20000)
    page.click("#place-listbox li[role=option] button >> nth=0")
    page.wait_for_selector("text=Is this your business?", timeout=20000)


def otp_and_file(page: Page, prefix: str) -> None:
    page.wait_for_selector("text=Enter the 4-digit code", timeout=20000)
    page.wait_for_selector("text=Tap to fill", timeout=20000)
    shot(page, f"{prefix}_code")
    page.click("text=Tap to fill")
    page.wait_for_selector("text=Review and submit", timeout=20000)
    shot(page, f"{prefix}_ready")
    page.get_by_role("button", name="Submit", exact=True).click()
    page.wait_for_selector("text=Verification #", timeout=20000)
    time.sleep(1.0)
    shot(page, f"{prefix}_dossier", full=True)


def scenario_onsite_sandbox_gst(page: Page) -> None:
    """On-site at Haldiram's + provider sandbox GSTIN -> NEEDS_REVIEW (test data, name conflict, look-alikes)."""
    page.goto(f"{URL}/verify")
    page.wait_for_selector("text=Are you at the business")
    shot(page, "a1_locate")
    page.click("text=Yes, I'm there")
    page.wait_for_selector("text=Businesses near you", timeout=20000)
    shot(page, "a2_nearby")
    page.click("button:has-text(\"Haldiram's - Murthal\")")
    page.wait_for_selector("text=Is this your business?", timeout=20000)
    shot(page, "a3_listing")
    page.click("text=Yes, that's us")
    page.click("text=Yes, I have a GSTIN")
    page.wait_for_selector("input[aria-label=GSTIN]")
    page.keyboard.type("00AAAAA0000A1Z", delay=30)
    shot(page, "a4_gstin_decoding")
    page.keyboard.type("T")
    page.wait_for_selector("text=Is this your GST registration?", timeout=20000)
    shot(page, "a5_gst_extract")
    page.click("text=Yes, that's us")
    page.wait_for_selector("text=Verify the business phone", timeout=20000)
    time.sleep(1.0)
    page.keyboard.type("12345", delay=50)
    time.sleep(1.0)
    shot(page, "a6_phone_mismatch")
    page.keyboard.type("99999", delay=50)
    otp_and_file(page, "a7")


def scenario_maps_no_gstin_verified(page: Page) -> None:
    """Scenario 3: on Google Maps, no GSTIN, OTP on the listing's own mobile -> VERIFIED."""
    remote_start(page)
    search_and_pick(page, "Burfiwala Murthal")
    page.click("text=Yes, that's us")
    page.click("text=No GSTIN")
    page.wait_for_selector("text=Verify the business phone", timeout=20000)
    time.sleep(1.0)
    shot(page, "b1_phone_listing")
    page.keyboard.type("50043", delay=50)        # +91 89•••••900 -> hidden 50043
    otp_and_file(page, "b2")


def scenario_duplicate_claim(page: Page) -> None:
    """Fraud: the same Google listing claimed again after it was verified -> NEEDS_REVIEW."""
    remote_start(page)
    search_and_pick(page, "Burfiwala Murthal")
    page.click("text=Yes, that's us")
    page.click("text=No GSTIN")
    page.wait_for_selector("text=Verify the business phone", timeout=20000)
    time.sleep(1.0)
    page.keyboard.type("50043", delay=50)
    otp_and_file(page, "c1_duplicate")


def scenario_invalid_gstin(page: Page) -> None:
    """Scenario 2: checksum-invalid GSTIN, nothing else -> UNVERIFIED."""
    remote_start(page)
    page.fill("input[role=combobox]", "Kaveri Textiles")
    time.sleep(1.2)
    page.click("text=Not on Google Maps? Continue as")
    page.click("text=Yes, I have a GSTIN")
    page.wait_for_selector("input[aria-label=GSTIN]")
    page.keyboard.type("29AAJCK4821M1Z2", delay=30)
    time.sleep(1.5)
    shot(page, "d1_invalid_checksum")
    page.click("text=Submit now")
    page.wait_for_selector("text=Verification #", timeout=20000)
    shot(page, "d2_invalid_dossier", full=True)


def scenario_unregistered_gstin(page: Page) -> None:
    """Scenario 2b: well-formed GSTIN that the register doesn't know -> UNVERIFIED."""
    remote_start(page)
    page.fill("input[role=combobox]", "Kaveri Textiles")
    time.sleep(1.2)
    page.click("text=Not on Google Maps? Continue as")
    page.click("text=Yes, I have a GSTIN")
    page.wait_for_selector("input[aria-label=GSTIN]")
    page.keyboard.type("29AAJCK4821M1Z1", delay=30)
    page.wait_for_selector("text=GSTIN not registered", timeout=20000)
    shot(page, "e1_not_registered")
    page.click("text=Submit now")
    page.wait_for_selector("text=Verification #", timeout=20000)
    shot(page, "e2_not_registered_dossier", full=True)


def scenario_landline_lookalikes(page: Page) -> None:
    """Scenario 5: 'Haldiram's' has look-alikes in the same PIN and a landline -> NEEDS_REVIEW."""
    remote_start(page)
    search_and_pick(page, "Haldiram's Murthal GT Karnal Road")
    page.click("text=Yes, that's us")
    page.click("text=No GSTIN")
    page.wait_for_selector("text=Verify the business phone", timeout=20000)
    time.sleep(1.0)
    shot(page, "f1_landline_targets")
    page.keyboard.type("9876501234", delay=40)
    otp_and_file(page, "f2_lookalikes")


SCENARIOS = [
    scenario_onsite_sandbox_gst,
    scenario_maps_no_gstin_verified,
    scenario_duplicate_claim,
    scenario_invalid_gstin,
    scenario_unregistered_gstin,
    scenario_landline_lookalikes,
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        for fn in SCENARIOS:
            if only and fn.__name__ not in only:
                continue
            print(fn.__name__)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, geolocation=HALDIRAM,
                                      permissions=["geolocation"])
            page = ctx.new_page()
            fn(page)
            ctx.close()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(URL)
        page.wait_for_load_state("networkidle")
        shot(page, "z_register")
        ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
