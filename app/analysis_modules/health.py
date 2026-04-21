from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any


SEVERITY_WEIGHTS = {
    "critical": 1.0,
    "warning": 0.55,
    "info": 0.2,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    # unix seconds / milliseconds
    if text.isdigit() and len(text) in (10, 13):
        try:
            ts = int(text)
            if len(text) == 13:
                ts = ts / 1000
            return datetime.fromtimestamp(ts)
        except Exception:
            return None

    candidates = [
        text,
        text.replace("Z", "+00:00"),
        text.replace(" ", "T", 1) if " " in text and "T" not in text else text,
    ]
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate)
        except Exception:
            continue
    return None


def filter_logs_for_tool(logs: list[dict[str, Any]], tool_id: str) -> list[dict[str, Any]]:
    out = []
    for log in logs:
        payload = log.get("payload", {}) or {}
        if str(payload.get("tool_id", "")).strip() == tool_id:
            out.append(log)
    return out


def compute_health_summary(tool_logs: list[dict[str, Any]]) -> dict[str, Any]:
    if not tool_logs:
        return {
            "tool_id": None,
            "health_score": 100,
            "avg_confidence": 0.0,
            "fault_rate": 0.0,
            "severity_breakdown": {"critical": 0, "warning": 0, "info": 0},
            "event_counts": {},
            "dominant_fault_type": None,
            "total_events": 0,
            "latest_event": None,
        }

    total = len(tool_logs)
    severity_counter: Counter[str] = Counter()
    event_counter: Counter[str] = Counter()
    confidence_values: list[float] = []
    latest: dict[str, Any] | None = None
    latest_dt: datetime | None = None

    weighted_fault_sum = 0.0
    for log in tool_logs:
        payload = log.get("payload", {}) or {}
        sev = str(payload.get("severity", "info")).lower().strip()
        if sev not in SEVERITY_WEIGHTS:
            sev = "info"
        severity_counter[sev] += 1

        event_type = str(payload.get("event_type", "unknown_event")).strip() or "unknown_event"
        event_counter[event_type] += 1

        conf = _safe_float(log.get("confidence", 0.0))
        confidence_values.append(conf)
        weighted_fault_sum += SEVERITY_WEIGHTS[sev]

        dt = _parse_timestamp(payload.get("timestamp") or log.get("created_at"))
        if latest_dt is None or (dt is not None and dt >= latest_dt):
            latest_dt = dt
            latest = log

    avg_confidence = sum(confidence_values) / max(len(confidence_values), 1)
    fault_rate = weighted_fault_sum / max(total, 1)

    # Health score derived from fault rate + avg confidence
    # Lower weighted fault rate and higher confidence = healthier tool.
    fault_penalty = min(70.0, fault_rate * 35.0)
    confidence_penalty = max(0.0, (1.0 - avg_confidence) * 30.0)
    health_score = max(0.0, round(100.0 - fault_penalty - confidence_penalty, 1))

    return {
        "tool_id": (latest or {}).get("payload", {}).get("tool_id"),
        "health_score": health_score,
        "avg_confidence": round(avg_confidence, 3),
        "fault_rate": round(fault_rate, 3),
        "severity_breakdown": {
            "critical": severity_counter.get("critical", 0),
            "warning": severity_counter.get("warning", 0),
            "info": severity_counter.get("info", 0),
        },
        "event_counts": dict(event_counter),
        "dominant_fault_type": event_counter.most_common(1)[0][0] if event_counter else None,
        "total_events": total,
        "latest_event": latest,
    }


def build_fault_timeline(tool_logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bucket: dict[str, Counter[str]] = defaultdict(Counter)

    for log in tool_logs:
        payload = log.get("payload", {}) or {}
        event_type = str(payload.get("event_type", "unknown_event")).strip() or "unknown_event"
        dt = _parse_timestamp(payload.get("timestamp") or log.get("created_at"))
        label = dt.strftime("%Y-%m-%d %H:00") if dt else str(log.get("created_at", "unknown"))[:13]
        bucket[label][event_type] += 1

    rows: list[dict[str, Any]] = []
    for period in sorted(bucket.keys()):
        for event_type, count in sorted(bucket[period].items()):
            rows.append({"period": period, "event_type": event_type, "count": count})
    return rows
