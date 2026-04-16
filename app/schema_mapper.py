import re
from typing import Any


CANONICAL_KEY_ALIASES = {
    "timestamp": {"timestamp", "time", "datetime", "date_time", "event_time"},
    "tool_id": {"tool_id", "toolid", "tool", "machine", "machine_id", "equipment_id"},
    "chamber_id": {"chamber_id", "chamber", "chamberid", "module", "module_id"},
    "temperature_c": {"temperature", "temp", "tempc", "temperature_c", "temp_c"},
    "pressure_pa": {"pressure", "pressure_pa", "pressure_text", "press", "p"},
    "error_code": {"error", "error_code", "code", "alarm", "alarm_code", "fault_code"},
    "severity": {"severity", "severitylevel", "level", "priority"},
    "raw_message": {"message", "msg", "description", "event", "log_event", "raw_message"},
    "sensor_id": {"sensor", "sensor_id", "sensorid"},
    "status": {"status", "state"},
}

BASE_FIELD_MAP = {
    "timestamp": "timestamp",
    "time": "timestamp",
    "datetime": "timestamp",
    "date_time": "timestamp",
    "event_time": "timestamp",
    "tool_id": "tool_id",
    "toolid": "tool_id",
    "tool": "tool_id",
    "machine": "tool_id",
    "machine_id": "tool_id",
    "equipment_id": "tool_id",
    "chamber_id": "chamber_id",
    "chamber": "chamber_id",
    "chamberid": "chamber_id",
    "module": "chamber_id",
    "module_id": "chamber_id",
    "temperature": "temperature_c",
    "temp": "temperature_c",
    "tempc": "temperature_c",
    "temperature_c": "temperature_c",
    "temp_c": "temperature_c",
    "pressure": "pressure_pa",
    "pressure_pa": "pressure_pa",
    "pressure_text": "pressure_pa",
    "press": "pressure_pa",
    "p": "pressure_pa",
    "error": "error_code",
    "error_code": "error_code",
    "code": "error_code",
    "alarm": "error_code",
    "alarm_code": "error_code",
    "fault_code": "error_code",
    "severity": "severity",
    "severitylevel": "severity",
    "level": "severity",
    "priority": "severity",
    "message": "raw_message",
    "msg": "raw_message",
    "description": "raw_message",
    "event": "raw_message",
    "log_event": "raw_message",
    "raw_message": "raw_message",
    "sensor": "sensor_id",
    "sensor_id": "sensor_id",
    "sensorid": "sensor_id",
    "status": "status",
    "state": "status",
}

EVENT_PATTERNS = {
    "vacuum_fault": [
        "vacuum pressure low",
        "vacuum low",
        "vacuum fault",
        "under-pressure",
        "pressure below threshold",
        "vacuum_failure",
    ],
    "thermal_fault": [
        "temperature high",
        "overheat",
        "overheating",
        "temperature rising rapidly",
        "thermal fault",
        "thermal_fault",
    ],
    "sensor_fault": [
        "sensor failure",
        "sensor fault",
        "signal lost",
        "sensor error",
        "measurement missing",
    ],
    "process_event": [
        "recipe started",
        "recipe step",
        "process started",
        "process completed",
        "processing",
        "wafer",
    ],
}


SEVERITY_PATTERNS = {
    "critical": ["critical", "alarm", "fatal", "error", "high"],
    "warning": ["warning", "warn", "medium"],
    "info": ["info", "normal", "low"],
}


def _clean_key(key: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", key.lower().replace(" ", "_"))


def _to_number_if_possible(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value

    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value

    # allow values like "95.2", "4", "0.8"
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except Exception:
            return value

    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except Exception:
            return value

    return value


def _normalize_user_rules(rules: dict[str, str]) -> dict[str, str]:
    normalized = {}
    for raw_key, canonical_key in rules.items():
        normalized[_clean_key(raw_key)] = canonical_key
    return normalized


def _canonical_from_alias(cleaned_key: str) -> str | None:
    for canonical, aliases in CANONICAL_KEY_ALIASES.items():
        if cleaned_key == canonical:
            return canonical
        if cleaned_key in aliases:
            return canonical
        for alias in aliases:
            if cleaned_key.endswith("_" + alias):
                return canonical
    return None


def _infer_event_type(payload: dict[str, Any], raw_text: str = "") -> str:
    searchable = []

    for key, value in payload.items():
        if isinstance(value, str):
            searchable.append(value.lower())
        searchable.append(str(key).lower())

    if raw_text:
        searchable.append(raw_text.lower())

    blob = " | ".join(searchable)

    for event_type, patterns in EVENT_PATTERNS.items():
        for pattern in patterns:
            if pattern in blob:
                return event_type

    return "unknown_event"


def _infer_severity(payload: dict[str, Any], raw_text: str = "") -> str:
    if "severity" in payload and payload["severity"]:
        sev = str(payload["severity"]).strip().lower()
        for canonical, patterns in SEVERITY_PATTERNS.items():
            if sev == canonical or sev in patterns:
                return canonical

    searchable = []

    for value in payload.values():
        if isinstance(value, str):
            searchable.append(value.lower())

    if raw_text:
        searchable.append(raw_text.lower())

    blob = " | ".join(searchable)

    for severity, patterns in SEVERITY_PATTERNS.items():
        for pattern in patterns:
            if pattern in blob:
                return severity

    return "info"


def _score_confidence(
    raw_payload: dict[str, Any],
    normalized_payload: dict[str, Any],
    unknown_keys: list[str],
) -> float:
    score = 0.2

    if normalized_payload.get("event_type") and normalized_payload["event_type"] != "unknown_event":
        score += 0.25

    if normalized_payload.get("severity"):
        score += 0.1

    important_fields = ["temperature_c", "pressure_pa", "chamber_id", "error_code", "tool_id", "timestamp"]
    filled = sum(1 for field in important_fields if normalized_payload.get(field) is not None)
    score += min(0.35, filled * 0.07)

    if raw_payload:
        known_ratio = (len(raw_payload) - len(unknown_keys)) / max(len(raw_payload), 1)
        score += 0.2 * known_ratio

    return round(min(1.0, max(0.0, score)), 3)


def normalize_payload(
    raw_payload: dict[str, Any],
    rules: dict[str, str] | None = None,
    raw_text: str = "",
) -> tuple[dict[str, Any], float]:
    """
    Normalize extracted payload into a canonical schema.

    Order of priority:
    1. User / memory rules
    2. Known aliases
    3. Keep remaining keys as-is only if useful
    4. Infer event_type and severity
    """

    rules = rules or {}
    normalized_rules = _normalize_user_rules(rules)

    normalized: dict[str, Any] = {}
    unknown_keys: list[str] = []

    for raw_key, raw_value in raw_payload.items():
        cleaned_key = _clean_key(str(raw_key))
        value = _to_number_if_possible(raw_value)

        canonical_key = None

        # 1. explicit rules
        if cleaned_key in normalized_rules:
            canonical_key = normalized_rules[cleaned_key]

        # 2. alias-based mapping
        if canonical_key is None:
            canonical_key = _canonical_from_alias(cleaned_key)

        # 3. store
        if canonical_key:
            if canonical_key == "timestamp":
                existing = normalized.get("timestamp")
                incoming = value

                if isinstance(existing, str) and "T" in existing:
                    pass
                elif isinstance(incoming, str) and "T" in incoming:
                    normalized["timestamp"] = incoming
                elif existing is None:
                    normalized["timestamp"] = incoming
            else:
                normalized[canonical_key] = value

    # Normalize special cases
    if "temperature_c" in normalized:
        normalized["temperature_c"] = _to_number_if_possible(normalized["temperature_c"])

    if "pressure_pa" in normalized:
        normalized["pressure_pa"] = _to_number_if_possible(normalized["pressure_pa"])

    if "chamber_id" in normalized:
        normalized["chamber_id"] = _to_number_if_possible(normalized["chamber_id"])

    # Infer semantics
    normalized["event_type"] = _infer_event_type(normalized, raw_text=raw_text)
    normalized["severity"] = _infer_severity(normalized, raw_text=raw_text)

    confidence = _score_confidence(raw_payload, normalized, unknown_keys)

    return normalized, confidence