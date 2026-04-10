from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

DB_PATH = os.getenv("DB_PATH", "log_pipeline.db")


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                format_detected TEXT NOT NULL,
                confidence REAL NOT NULL,
                needs_review INTEGER NOT NULL,
                payload TEXT NOT NULL,
                explanation TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_key TEXT UNIQUE NOT NULL,
                canonical_key TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def store_log(
    format_detected: str,
    confidence: float,
    needs_review: bool,
    payload: dict[str, Any],
    explanation: str,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO logs (format_detected, confidence, needs_review, payload, explanation)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                format_detected,
                confidence,
                int(needs_review),
                json.dumps(payload),
                explanation,
            ),
        )
        return int(cur.lastrowid)


def fetch_logs(limit: int = 100) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, format_detected, confidence, needs_review, payload, explanation, created_at
            FROM logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "format_detected": row["format_detected"],
            "confidence": row["confidence"],
            "needs_review": bool(row["needs_review"]),
            "payload": json.loads(row["payload"]),
            "explanation": row["explanation"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def fetch_log(log_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, format_detected, confidence, needs_review, payload, explanation, created_at
            FROM logs WHERE id = ?
            """,
            (log_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "format_detected": row["format_detected"],
        "confidence": row["confidence"],
        "needs_review": bool(row["needs_review"]),
        "payload": json.loads(row["payload"]),
        "explanation": row["explanation"],
        "created_at": row["created_at"],
    }


def upsert_schema_rule(raw_key: str, canonical_key: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO schema_rules (raw_key, canonical_key)
            VALUES (?, ?)
            ON CONFLICT(raw_key) DO UPDATE SET canonical_key = excluded.canonical_key
            """,
            (raw_key.lower(), canonical_key.lower()),
        )


def get_schema_rules() -> dict[str, str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT raw_key, canonical_key FROM schema_rules"
        ).fetchall()
    return {row["raw_key"]: row["canonical_key"] for row in rows}


def get_stats() -> dict[str, Any]:
    with get_conn() as conn:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                AVG(confidence) AS avg_confidence,
                SUM(CASE WHEN needs_review = 1 THEN 1 ELSE 0 END) AS needs_review_count
            FROM logs
            """
        ).fetchone()
    total = int(totals["total"] or 0)
    return {
        "total_logs": total,
        "avg_confidence": float(totals["avg_confidence"] or 0.0),
        "needs_review_count": int(totals["needs_review_count"] or 0),
    }
