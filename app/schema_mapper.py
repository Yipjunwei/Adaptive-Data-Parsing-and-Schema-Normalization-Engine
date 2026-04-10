from __future__ import annotations

from typing import Any

BASE_FIELD_MAP = {
    "temp": "temperature_c",
    "temperature": "temperature_c",
    "t": "temperature_c",
    "vac": "vacuum_pressure",
    "vacuum": "vacuum_pressure",
    "pressure": "vacuum_pressure",
    "p": "vacuum_pressure",
    "err": "error_code",
    "error": "error_code",
    "alarm": "error_code",
    "chamber": "chamber_id",
    "chamberx": "chamber_id",
    "tool": "tool_id",
    "timestamp": "timestamp",
}

EVENT_MAP = {
    "vac low": "vacuum_fault",
    "vacuum pressure low": "vacuum_fault",
    "vacuum pressure below threshold": "vacuum_fault",
    "overheat": "thermal_fault",
    "temp high": "thermal_fault",
    "temperature high": "thermal_fault",
    "error": "generic_error",
}


def infer_event_type(raw_text: str, current: str | None = None) -> str:
    if current:
        cur = current.lower().strip()
        for key, event in EVENT_MAP.items():
            if key in cur:
                return event
        return cur.replace(" ", "_")

    low = raw_text.lower()
    for key, event in EVENT_MAP.items():
        if key in low:
            return event
    return "unknown_event"


def normalize_payload(
    payload: dict[str, Any],
    learned_rules: dict[str, str],
    raw_text: str = "",
) -> tuple[dict[str, Any], float]:
    normalized: dict[str, Any] = {}

    known_hits = 0
    unknown_hits = 0

    merged_map = BASE_FIELD_MAP | learned_rules

    for key, value in payload.items():
        key_l = key.lower().strip()
        canonical = merged_map.get(key_l)
        if canonical:
            known_hits += 1
            normalized[canonical] = _coerce_value(canonical, value)
        else:
            unknown_hits += 1
            normalized[key_l] = value

    event_from_field = payload.get("event_type") or payload.get("event")
    normalized["event_type"] = infer_event_type(raw_text, str(event_from_field) if event_from_field else None)

    if "severity" not in normalized:
        normalized["severity"] = infer_severity(raw_text, normalized)

    total = known_hits + unknown_hits
    confidence = (known_hits / total) if total else 0.5

    if normalized["event_type"] != "unknown_event":
        confidence = min(1.0, confidence + 0.1)

    return normalized, round(confidence, 3)


def infer_severity(raw_text: str, normalized: dict[str, Any]) -> str:
    low = raw_text.lower()
    if any(tok in low for tok in ["critical", "alarm", "fault", "error"]):
        return "critical"

    pressure = normalized.get("vacuum_pressure")
    if isinstance(pressure, (int, float)) and pressure < 1.0:
        return "critical"

    temp = normalized.get("temperature_c")
    if isinstance(temp, (int, float)) and temp >= 90:
        return "high"

    return "medium"


def _coerce_value(canonical_key: str, value: Any) -> Any:
    if canonical_key in {"temperature_c", "vacuum_pressure"}:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value

    if canonical_key in {"chamber_id"}:
        try:
            return int(str(value).strip("#"))
        except (TypeError, ValueError):
            return value

    return value
