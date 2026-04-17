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

# Weighted regex patterns: stronger, more specific phrases get more weight.
EVENT_PATTERNS = {
    "vacuum_fault": [
        (r"vacuum pressure low", 1.0),
        (r"pressure below threshold", 0.95),
        (r"vacuum fault", 0.9),
        (r"under[-\s]?pressure", 0.9),
        (r"vacuum_failure", 0.9),
        (r"\bvacuum low\b", 0.75),
        (r"\bvac\b", 0.35),
    ],
    "thermal_fault": [
        (r"temperature rising rapidly", 1.0),
        (r"temperature high", 0.95),
        (r"thermal fault", 0.9),
        (r"overheat(?:ing)?", 0.9),
        (r"thermal_fault", 0.9),
        (r"\btemp(?:erature)?\b", 0.35),
        (r"\bheat\b", 0.3),
    ],
    "sensor_fault": [
        (r"sensor failure", 0.95),
        (r"sensor fault", 0.95),
        (r"signal lost", 0.9),
        (r"sensor error", 0.9),
        (r"measurement missing", 0.85),
    ],
    "process_event": [
        (r"recipe started", 0.9),
        (r"recipe step", 0.85),
        (r"process started", 0.85),
        (r"process completed", 0.85),
        (r"processing", 0.55),
        (r"wafer", 0.45),
    ],
}

SEVERITY_PATTERNS = {
    "critical": ["critical", "alarm", "fatal", "error", "high"],
    "warning": ["warning", "warn", "medium"],
    "info": ["info", "normal", "low"],
}


CRITICAL_FIELDS = ["event_type", "timestamp", "tool_id"]
IMPORTANT_FIELDS = ["temperature_c", "pressure_pa", "chamber_id", "error_code", "tool_id", "timestamp"]


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


def _build_search_blob(payload: dict[str, Any], raw_text: str = "") -> str:
    searchable = []
    for key, value in payload.items():
        searchable.append(str(key).lower())
        if isinstance(value, str):
            searchable.append(value.lower())
        elif value is not None:
            searchable.append(str(value).lower())
    if raw_text:
        searchable.append(raw_text.lower())
    return " | ".join(searchable)


def _infer_event_from_text(payload: dict[str, Any], raw_text: str = "") -> tuple[str, float, dict[str, float]]:
    blob = _build_search_blob(payload, raw_text)
    scores: dict[str, float] = {}

    for event_type, patterns in EVENT_PATTERNS.items():
        best = 0.0
        for pattern, weight in patterns:
            if re.search(pattern, blob, re.IGNORECASE):
                best = max(best, weight)
        if best > 0:
            scores[event_type] = best

    if not scores:
        return "unknown_event", 0.0, {}

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_type, best_score = ordered[0]
    return best_type, best_score, scores


def _infer_event_from_values(payload: dict[str, Any]) -> tuple[str | None, float]:
    temp = payload.get("temperature_c")
    pressure = payload.get("pressure_pa")
    error_code = str(payload.get("error_code", "")).lower()
    status = str(payload.get("status", "")).lower()

    if isinstance(temp, (int, float)) and temp >= 180:
        return "thermal_fault", 0.78

    if isinstance(pressure, (int, float)) and 0 <= pressure <= 80:
        return "vacuum_fault", 0.78

    if "sensor" in error_code or ("sensor" in status and "fault" in status):
        return "sensor_fault", 0.72

    return None, 0.0


def _infer_event_type(payload: dict[str, Any], raw_text: str = "") -> tuple[str, dict[str, Any]]:
    text_event, text_score, candidate_scores = _infer_event_from_text(payload, raw_text)
    value_event, value_score = _infer_event_from_values(payload)

    event_type = text_event
    event_score = text_score
    source = "text"

    if value_event and value_score > event_score:
        event_type = value_event
        event_score = value_score
        source = "values"

    if text_event != "unknown_event" and value_event and text_event != value_event:
        if max(text_score, value_score) < 0.85:
            event_type = "unknown_event"
            source = "conflict"
            event_score = max(text_score, value_score) * 0.5

    ordered_scores = sorted(candidate_scores.values(), reverse=True)
    ambiguous = len(ordered_scores) >= 2 and (ordered_scores[0] - ordered_scores[1]) < 0.15

    if ambiguous and event_score < 0.9:
        event_type = "unknown_event"

    if event_score < 0.55:
        event_type = "unknown_event"

    return event_type, {
        "event_score": round(event_score, 3),
        "event_source": source,
        "ambiguous_event": ambiguous,
        "candidate_event_scores": {k: round(v, 3) for k, v in candidate_scores.items()},
        "value_event": value_event,
        "value_event_score": round(value_score, 3),
    }


def _infer_severity(payload: dict[str, Any], raw_text: str = "") -> str:
    if "severity" in payload and payload["severity"]:
        sev = str(payload["severity"]).strip().lower()
        for canonical, patterns in SEVERITY_PATTERNS.items():
            if sev == canonical or sev in patterns:
                return canonical

    blob = _build_search_blob(payload, raw_text)
    for severity, patterns in SEVERITY_PATTERNS.items():
        for pattern in patterns:
            if pattern in blob:
                return severity

    return "info"


def _is_timestamp_like(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return value > 1_000_000_000
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(
        re.search(r"\d{4}-\d{2}-\d{2}", text)
        or "T" in text
        or ":" in text
        or re.fullmatch(r"\d{10,13}", text)
    )


def _field_validation_scores(payload: dict[str, Any]) -> dict[str, float]:
    checks: dict[str, float] = {}

    ts = payload.get("timestamp")
    checks["timestamp"] = 1.0 if _is_timestamp_like(ts) else 0.0

    tool = payload.get("tool_id")
    checks["tool_id"] = 1.0 if isinstance(tool, (str, int, float)) and str(tool).strip() else 0.0

    chamber = payload.get("chamber_id")
    checks["chamber_id"] = 1.0 if isinstance(chamber, (str, int, float)) and str(chamber).strip() else 0.0

    temp = payload.get("temperature_c")
    checks["temperature_c"] = 1.0 if isinstance(temp, (int, float)) and -50 <= temp <= 500 else 0.0

    pressure = payload.get("pressure_pa")
    checks["pressure_pa"] = 1.0 if isinstance(pressure, (int, float)) and 0 <= pressure <= 2_000_000 else 0.0

    error_code = payload.get("error_code")
    checks["error_code"] = 1.0 if isinstance(error_code, (str, int, float)) and str(error_code).strip() else 0.0

    sev = str(payload.get("severity", "")).strip().lower()
    checks["severity"] = 1.0 if sev in {"critical", "warning", "info"} else 0.0

    return checks


def _consistency_penalty(payload: dict[str, Any]) -> tuple[float, list[str]]:
    penalty = 0.0
    issues: list[str] = []

    event_type = payload.get("event_type")
    temp = payload.get("temperature_c")
    pressure = payload.get("pressure_pa")
    status = str(payload.get("status", "")).lower().strip()
    severity = str(payload.get("severity", "")).lower().strip()

    if event_type == "thermal_fault" and not isinstance(temp, (int, float)):
        penalty += 0.15
        issues.append("thermal_fault_without_temperature")

    if event_type == "vacuum_fault" and not isinstance(pressure, (int, float)):
        penalty += 0.15
        issues.append("vacuum_fault_without_pressure")

    if event_type == "sensor_fault" and not payload.get("sensor_id") and "sensor" not in str(payload.get("raw_message", "")).lower():
        penalty += 0.1
        issues.append("sensor_fault_without_sensor_context")

    if severity == "critical" and status == "normal":
        penalty += 0.1
        issues.append("critical_severity_with_normal_status")

    if isinstance(temp, (int, float)) and temp >= 180 and event_type == "process_event":
        penalty += 0.08
        issues.append("process_event_with_extreme_temperature")

    return round(penalty, 3), issues


def _missing_critical_fields(payload: dict[str, Any]) -> list[str]:
    missing = []
    for field in CRITICAL_FIELDS:
        value = payload.get(field)
        if value is None or value == "" or value == "unknown_event":
            missing.append(field)
    return missing


def _sparse_parse(raw_payload: dict[str, Any]) -> bool:
    useful = [k for k in raw_payload.keys() if str(k).lower() not in {"raw", "raw_text"}]
    return len(useful) < 2


def _mapping_quality(raw_payload: dict[str, Any], unknown_keys: list[str]) -> float:
    if not raw_payload:
        return 0.0
    return (len(raw_payload) - len(unknown_keys)) / max(len(raw_payload), 1)


def assess_payload(
    raw_payload: dict[str, Any],
    normalized_payload: dict[str, Any],
    raw_text: str = "",
    profile_reliability_bonus: float = 0.0,
) -> dict[str, Any]:
    validation_scores = _field_validation_scores(normalized_payload)
    event_meta = normalized_payload.pop("_event_meta", None) or {}
    missing_critical = _missing_critical_fields(normalized_payload)
    consistency_penalty, consistency_issues = _consistency_penalty(normalized_payload)
    sparse_parse = _sparse_parse(raw_payload)
    ambiguity_penalty = 0.08 if event_meta.get("ambiguous_event") else 0.0
    sparse_penalty = 0.08 if sparse_parse else 0.0

    mapping_quality = _mapping_quality(raw_payload, [])
    important_validated = sum(validation_scores.get(field, 0.0) for field in IMPORTANT_FIELDS)

    breakdown = {
        "base_score": 0.2,
        "event_score": round(min(0.25, event_meta.get("event_score", 0.0) * 0.25), 3),
        "severity_score": 0.1 if validation_scores.get("severity", 0.0) == 1.0 else 0.0,
        "validated_field_score": round(min(0.35, important_validated * (0.35 / len(IMPORTANT_FIELDS))), 3),
        "mapping_quality_score": round(0.2 * mapping_quality, 3),
        "profile_reliability_bonus": round(profile_reliability_bonus, 3),
        "consistency_penalty": round(-consistency_penalty, 3),
        "ambiguity_penalty": round(-ambiguity_penalty, 3),
        "sparse_parse_penalty": round(-sparse_penalty, 3),
    }

    confidence = sum(breakdown.values())
    confidence = round(min(0.99, max(0.0, confidence)), 3)

    return {
        "confidence": confidence,
        "confidence_breakdown": breakdown,
        "validation_scores": validation_scores,
        "missing_critical_fields": missing_critical,
        "consistency_issues": consistency_issues,
        "event_metadata": event_meta,
        "signals": {
            "ambiguous_event": bool(event_meta.get("ambiguous_event")),
            "sparse_parse": sparse_parse,
            "missing_critical_fields": bool(missing_critical),
            "has_consistency_issues": bool(consistency_issues),
        },
    }


def normalize_payload(
    raw_payload: dict[str, Any],
    rules: dict[str, str] | None = None,
    raw_text: str = "",
    profile_reliability_bonus: float = 0.0,
) -> tuple[dict[str, Any], float, dict[str, Any]]:
    """
    Normalize extracted payload into a canonical schema and return:
    - normalized payload
    - confidence score
    - assessment metadata / breakdown
    """

    rules = rules or {}
    normalized_rules = _normalize_user_rules(rules)

    normalized: dict[str, Any] = {}
    unknown_keys: list[str] = []

    for raw_key, raw_value in raw_payload.items():
        cleaned_key = _clean_key(str(raw_key))
        value = _to_number_if_possible(raw_value)

        canonical_key = None

        if cleaned_key in normalized_rules:
            canonical_key = normalized_rules[cleaned_key]

        if canonical_key is None:
            canonical_key = _canonical_from_alias(cleaned_key)

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
        else:
            unknown_keys.append(cleaned_key)

    if "temperature_c" in normalized:
        normalized["temperature_c"] = _to_number_if_possible(normalized["temperature_c"])

    if "pressure_pa" in normalized:
        normalized["pressure_pa"] = _to_number_if_possible(normalized["pressure_pa"])

    if "chamber_id" in normalized:
        normalized["chamber_id"] = _to_number_if_possible(normalized["chamber_id"])

    event_type, event_meta = _infer_event_type(normalized, raw_text=raw_text)
    normalized["event_type"] = event_type
    normalized["severity"] = _infer_severity(normalized, raw_text=raw_text)
    normalized["_event_meta"] = event_meta

    assessment = assess_payload(
        raw_payload=raw_payload,
        normalized_payload=normalized,
        raw_text=raw_text,
        profile_reliability_bonus=profile_reliability_bonus,
    )

    normalized.pop("_event_meta", None)
    assessment["unknown_keys"] = unknown_keys
    assessment["mapping_quality"] = round(_mapping_quality(raw_payload, unknown_keys), 3)

    return normalized, assessment["confidence"], assessment
