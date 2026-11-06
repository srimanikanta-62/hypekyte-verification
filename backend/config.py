"""Environment configuration and the API error type shared by all modules."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
GSTIN_API_KEY = os.getenv("GSTIN_API_KEY", "").strip()

# simulated: OTP is delivered to the on-page virtual phone (no SMS provider).
OTP_MODE = os.getenv("OTP_MODE", "simulated").strip().lower()
# simulated: GST-registered mobile for real GSTINs comes from fixtures/demo_contacts.json
# live: call gstinapi.in /contact (paid accounts only). The sandbox GSTIN is always live.
GST_CONTACT_MODE = os.getenv("GST_CONTACT_MODE", "simulated").strip().lower()

SANDBOX_GSTIN = "00AAAAA0000A1ZT"
FIXTURES_DIR = BASE_DIR / "fixtures"

CORS_ORIGINS = [
    o.strip() for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",") if o.strip()
]


class ApiError(Exception):
    """An error with a stable machine-readable code the frontend maps to a toast."""

    def __init__(self, code: str, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra
