"""One-time codes for phone control.

OTP_MODE=simulated: no SMS is sent. The message is written to a per-session inbox that the
frontend's "virtual phone" reads via GET /api/dev/sms/{session_id}. Everything downstream
(hashing, expiry, attempt limits, resend cooldown) is the same code a real sender would use,
so swapping in a provider means implementing `SmsSender.send` only.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from config import OTP_MODE, ApiError

CODE_LENGTH = 4            # demo; production should use 6
TTL_S = 120
MAX_VERIFY_ATTEMPTS = 3
RESEND_COOLDOWN_S = 30
MAX_SENDS = 4


def _hash(session_id: str, code: str) -> str:
    return hashlib.sha256(f"{session_id}:{code}".encode()).hexdigest()


class SmsSender:
    def send(self, state: dict, to: str, body: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class SimulatedSmsSender(SmsSender):
    def send(self, state: dict, to: str, body: str) -> None:
        state.setdefault("sms_inbox", []).append({
            "id": secrets.token_hex(4),
            "to": f"+91 {to[:2]}•••••{to[7:]}",
            "sender": "HK-VERIFY",
            "body": body,
            "at": time.time(),
        })


def sender() -> SmsSender:
    if OTP_MODE == "simulated":
        return SimulatedSmsSender()
    raise ApiError("OTP_PROVIDER_MISSING", "No live SMS provider is configured (set OTP_MODE=simulated).", 500)


def send(state: dict, session_id: str, phone: str) -> dict:
    otp = state.get("otp") or {}
    now = time.time()
    if otp.get("sent_at") and now - otp["sent_at"] < RESEND_COOLDOWN_S and otp.get("phone") == phone:
        wait = int(RESEND_COOLDOWN_S - (now - otp["sent_at"])) + 1
        raise ApiError("OTP_COOLDOWN", f"A code was just sent. You can resend in {wait}s.", 429, retry_in=wait)
    sends = otp.get("sends", 0) if otp.get("phone") == phone else 0
    if sends >= MAX_SENDS:
        raise ApiError("OTP_SEND_LIMIT", "Too many codes requested for this number. Start again later.", 429)

    code = "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))
    state["otp"] = {
        "phone": phone,
        "hash": _hash(session_id, code),
        "sent_at": now,
        "expires_at": now + TTL_S,
        "attempts": 0,
        "sends": sends + 1,
        "verified": False,
    }
    sender().send(state, phone, f"{code} is your HypeKyte verification code. It expires in "
                                f"{TTL_S // 60} minutes. Never share it.")
    return {"expires_in": TTL_S, "resend_in": RESEND_COOLDOWN_S, "length": CODE_LENGTH,
            "mode": OTP_MODE}


def verify(state: dict, session_id: str, code: str) -> None:
    otp = state.get("otp")
    if not otp:
        raise ApiError("OTP_NOT_SENT", "Request a code first.", 400)
    if otp.get("verified"):
        return
    if time.time() > otp["expires_at"]:
        raise ApiError("OTP_EXPIRED", "That code has expired. Send a new one.", 410)
    if otp["attempts"] >= MAX_VERIFY_ATTEMPTS:
        raise ApiError("OTP_ATTEMPTS_EXCEEDED", "Too many wrong codes. Send a new one.", 429)

    otp["attempts"] += 1
    if not hmac.compare_digest(otp["hash"], _hash(session_id, (code or "").strip())):
        left = MAX_VERIFY_ATTEMPTS - otp["attempts"]
        raise ApiError("OTP_INVALID", "That code doesn't match." + (f" {left} tries left." if left else ""),
                       422, attempts_left=left)
    otp["verified"] = True
    otp["verified_at"] = time.time()
