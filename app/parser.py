from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from app.llm import parse_unstructured_with_llm

KV_PATTERN = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*=\s*([\w\.-]+)")
CHAMBER_PATTERN = re.compile(r"chamber\s*([0-9]+|[A-Za-z])", re.IGNORECASE)
ALARM_PATTERN = re.compile(r"alarm\s*([0-9]+)", re.IGNORECASE)


def parse_content(content: str, detected_format: str, guidance: dict | None = None) -> dict[str, Any]:
    if detected_format == "json":
        return _parse_json(content)
    if detected_format == "xml":
        return _parse_xml(content)
    if detected_format == "csv":
        return _parse_csv(content)
    return _parse_text(content, guidance=guidance)


def _parse_json(content: str) -> dict[str, Any]:
    data = json.loads(content)
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return {"raw": str(data)}
    return _flatten_dict(data)


def _parse_xml(content: str) -> dict[str, Any]:
    import xmltodict

    data = xmltodict.parse(content)
    root = next(iter(data.values()), {})

    metadata = root.get("metadata", {})
    system = root.get("system", {})
    events = root.get("events", {}).get("event", [])

    if isinstance(events, dict):
        events = [events]

    primary_event = events[0] if events else {}

    combined = {
        "metadata": metadata,
        "event": primary_event,
        "system": system,
    }

    return _flatten_dict(combined)


def _parse_csv(content: str) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(content))
    row = next(reader, None)
    if row is None:
        return {}
    return {str(k): v for k, v in row.items()}


def _parse_text(content: str, guidance: dict | None = None) -> dict[str, Any]:
    extracted: dict[str, Any] = {}

    for key, value in KV_PATTERN.findall(content):
        extracted[key] = value

    alarm = ALARM_PATTERN.search(content)
    if alarm:
        extracted.setdefault("alarm", alarm.group(1))

    chamber = CHAMBER_PATTERN.search(content)
    if chamber:
        extracted.setdefault("chamber", chamber.group(1))

    if "event_type" not in extracted:
        lower = content.lower()
        if "vac" in lower:
            extracted["event_type"] = "vacuum pressure low"
        elif "temp" in lower or "heat" in lower:
            extracted["event_type"] = "temperature high"

    should_use_llm = (
        not extracted
        or guidance is not None
        or len(extracted) <= 1
    )

    if should_use_llm:
        try:
            llm_data = parse_unstructured_with_llm(content, guidance=guidance)
            if llm_data:
                return {str(k): v for k, v in llm_data.items()}
        except Exception:
            pass

    if not extracted:
        return {"raw_text": content.strip()}

    return extracted


def _flatten_dict(data: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}

    if isinstance(data, dict):
        for key, value in data.items():
            clean_key = str(key).replace("@", "").replace("#text", "text")
            next_prefix = f"{prefix}_{clean_key}" if prefix else clean_key
            out.update(_flatten_dict(value, next_prefix))

    elif isinstance(data, list):
        if data:
            out.update(_flatten_dict(data[0], prefix))

    else:
        out[prefix] = data

    return out