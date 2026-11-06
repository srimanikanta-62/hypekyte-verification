"""SQLite persistence: verification sessions, provider cache and final verifications."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DATABASE_PATH = Path(__file__).resolve().parent / "hypekyte.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_cache (
                cache_key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                fetched_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                business_name TEXT NOT NULL,
                business_category TEXT,
                address TEXT,
                gstin TEXT,
                place_id TEXT,
                phone_masked TEXT,
                status TEXT NOT NULL,
                score INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_verifications_gstin ON verifications(gstin);
            CREATE INDEX IF NOT EXISTS idx_verifications_place ON verifications(place_id);
        """)


# ------------------------------------------------------------------- sessions
def insert_session(session_id: str, state: dict) -> None:
    now = time.time()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (id, state_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, json.dumps(state), now, now),
        )


def load_session(session_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT state_json FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return json.loads(row["state_json"]) if row else None


def save_session(session_id: str, state: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET state_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(state), time.time(), session_id),
        )


# -------------------------------------------------------------- provider cache
def cache_get(key: str, max_age_s: float) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT payload_json, fetched_at FROM provider_cache WHERE cache_key = ?", (key,)
        ).fetchone()
    if not row or time.time() - row["fetched_at"] > max_age_s:
        return None
    return json.loads(row["payload_json"])


def cache_put(key: str, payload: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO provider_cache (cache_key, payload_json, fetched_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload), time.time()),
        )


# --------------------------------------------------------------- verifications
def save_verification(session_id: str, summary: dict, result: dict) -> int:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM verifications WHERE session_id = ?", (session_id,)
        ).fetchone()
        values = (
            summary["business_name"], summary.get("business_category"), summary.get("address"),
            summary.get("gstin"), summary.get("place_id"), summary.get("phone_masked"),
            result["status"], int(result["score"]), json.dumps(result),
        )
        if existing:
            conn.execute("""
                UPDATE verifications SET business_name=?, business_category=?, address=?, gstin=?,
                    place_id=?, phone_masked=?, status=?, score=?, result_json=?
                WHERE id = ?""", (*values, existing["id"]))
            return int(existing["id"])
        cursor = conn.execute("""
            INSERT INTO verifications (business_name, business_category, address, gstin, place_id,
                phone_masked, status, score, result_json, session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (*values, session_id))
        return int(cursor.lastrowid)


def find_prior_claims(gstin: str | None, place_id: str | None, exclude_session: str) -> list[dict]:
    """Earlier VERIFIED registrations that used the same GSTIN or Google listing."""
    if not gstin and not place_id:
        return []
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, business_name, gstin, place_id, created_at FROM verifications
            WHERE status = 'VERIFIED' AND session_id != ?
              AND ((? IS NOT NULL AND gstin = ?) OR (? IS NOT NULL AND place_id = ?))
        """, (exclude_session, gstin, gstin, place_id, place_id)).fetchall()
    return [dict(r) for r in rows]


def list_verifications() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, business_name, business_category, gstin, place_id, phone_masked,
                   status, score, created_at FROM verifications ORDER BY id DESC
        """).fetchall()
    return [dict(r) for r in rows]


def get_verification(verification_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM verifications WHERE id = ?", (verification_id,)).fetchone()
    if not row:
        return None
    record = dict(row)
    record["result"] = json.loads(record.pop("result_json"))
    return record
