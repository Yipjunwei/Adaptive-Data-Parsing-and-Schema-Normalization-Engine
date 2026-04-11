from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from app.db import infer_event_from_memory as db_infer_event_from_memory
from app.db import upsert_event_memory, upsert_key_memory
from app.schema_mapper import BASE_FIELD_MAP

CANONICAL_KEYS = {
    "temperature_c",
    "vacuum_pressure",
    "error_code",
    "chamber_id",
    "tool_id",
    "timestamp",
}

HINTS: dict[str, tuple[str, float]] = {
    "tmp": ("temperature_c", 0.93),
    "temp": ("temperature_c", 0.95),
    "temperature": ("temperature_c", 0.96),
    "vac": ("vacuum_pressure", 0.92),
    "pressure": ("vacuum_pressure", 0.9),
    "alarm": ("error_code", 0.92),
    "err": ("error_code", 0.9),
    "error": ("error_code", 0.92),
    "chamber": ("chamber_id", 0.95),
    "tool": ("tool_id", 0.95),
    "time": ("timestamp", 0.88),
}


def guess_canonical_key(raw_key: str) -> tuple[str, float] | None:
    key = raw_key.lower().strip()
    if not key:
        return None

    if key in BASE_FIELD_MAP:
        return BASE_FIELD_MAP[key], 1.0

    for token, mapped in HINTS.items():
        if token in key:
            return mapped

    best_key = None
    best_ratio = 0.0
    for canonical in CANONICAL_KEYS:
        ratio = SequenceMatcher(None, key, canonical).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_key = canonical

    if best_key and best_ratio >= 0.72:
        return best_key, round(best_ratio, 3)

    return None


def learn_from_ingestion(
    raw_payload: dict[str, Any],
    normalized_payload: dict[str, Any],
    raw_text: str,
) -> None:
    for raw_key in raw_payload.keys():
        guessed = guess_canonical_key(str(raw_key))
        if guessed is None:
            continue

        canonical, confidence = guessed
        if canonical == raw_key.lower().strip():
            continue

        upsert_key_memory(str(raw_key), canonical, confidence)

    event_type = str(normalized_payload.get("event_type", "")).lower().strip()
    if event_type and event_type != "unknown_event":
        raw_event_phrase = raw_payload.get("event") or raw_payload.get("event_type")
        if isinstance(raw_event_phrase, str) and raw_event_phrase.strip():
            upsert_event_memory(raw_event_phrase, event_type)
        else:
            compact = _compact_text(raw_text)
            if compact:
                upsert_event_memory(compact, event_type)


def recall_event(raw_text: str) -> str | None:
    return db_infer_event_from_memory(raw_text)


def _compact_text(raw_text: str, max_len: int = 80) -> str:
    return " ".join(raw_text.split()).lower().strip()[:max_len]
