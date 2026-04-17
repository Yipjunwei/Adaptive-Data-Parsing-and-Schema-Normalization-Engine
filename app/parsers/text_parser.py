from __future__ import annotations

import re
from typing import Any

from app.parsers.base import BaseParser

KV_PATTERN = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*=\s*([\w\.\-:]+)")
CHAMBER_PATTERN = re.compile(r"chamber\s*([0-9]+|[A-Za-z])", re.IGNORECASE)
ALARM_PATTERN = re.compile(r"alarm\s*([A-Za-z0-9_\-]+)", re.IGNORECASE)

# --- Timestamp patterns ordered most-specific to least-specific ---
# Each tuple: (compiled_regex, format_hint)
_TIMESTAMP_PATTERNS: list[tuple[re.Pattern, str]] = [
    # ISO 8601 with timezone:  2024-04-15T12:03:20+08:00
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}"), "iso8601_tz"),
    # ISO 8601:  2024-04-15T12:03:20  or  2024-04-15T12:03:20.123
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"), "iso8601"),
    # Bracket-wrapped datetime:  [2024-04-15 12:03:20]
    (re.compile(r"\[\s*(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*\]"), "bracketed"),
    # Space-separated datetime:  2024-04-15 12:03:20
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"), "datetime_space"),
    # Date only:  2024-04-15
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "date_only"),
    # Unix epoch (10-digit seconds or 13-digit ms):  1713182600
    (re.compile(r"\b(1[0-9]{9}|[2-9][0-9]{9}|[0-9]{13})\b"), "unix_epoch"),
]

# --- Tool ID patterns ---
_TOOL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:tool|machine|equipment|unit)[_\s\-]?(?:id[_\s\-]?)?[:=\s]+([A-Za-z0-9_\-]+)", re.IGNORECASE),
    re.compile(r"\b([A-Z]{2,}[_\-]?(?:TOOL|ETCH|CVD|PVD|CMP|IMP|ALD|EUV|DUV|SCAN)[_\-]?\d*)\b"),
    re.compile(r"\b(TOOL[_\-]?\d+)\b", re.IGNORECASE),
]

# --- Sensor ID patterns ---
_SENSOR_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:sensor)[_\s\-]?(?:id)?[:=\s]+([A-Za-z0-9_\-]+)", re.IGNORECASE),
    re.compile(r"\b(SENSOR[_\-]?\d+)\b", re.IGNORECASE),
]

# --- Numeric value patterns for key sensor fields ---
_TEMP_PATTERN = re.compile(
    r"(?:temp(?:erature)?|TEMP)[_\s\-]*(?:c|celsius)?[:=\s]+([+-]?\d+(?:\.\d+)?)", re.IGNORECASE
)
_PRESSURE_PATTERN = re.compile(
    r"(?:pressure|press|vac(?:uum)?)[_\s\-]*(?:pa|bar|torr)?[:=\s]+([+-]?\d+(?:\.\d+)?)", re.IGNORECASE
)
_ERROR_CODE_PATTERN = re.compile(
    r"(?:error|err|alarm|fault|code)[_\s\-]*(?:code|no|num)?[:=\s]+([A-Za-z0-9_\-]+)", re.IGNORECASE
)
_SEVERITY_PATTERN = re.compile(
    r"(?:severity|level|priority)[:=\s]+([A-Za-z]+)", re.IGNORECASE
)
_STATUS_PATTERN = re.compile(
    r"\bstatus[:=\s]+([A-Za-z0-9_\-]+)", re.IGNORECASE
)


def _extract_timestamp(content: str) -> str | None:
    for pattern, hint in _TIMESTAMP_PATTERNS:
        m = pattern.search(content)
        if m:
            # bracketed pattern captures group 1; others capture the full match
            return m.group(1) if m.lastindex and m.lastindex >= 1 and hint == "bracketed" else m.group(0)
    return None


def _extract_tool_id(content: str) -> str | None:
    for pattern in _TOOL_PATTERNS:
        m = pattern.search(content)
        if m:
            return m.group(1)
    return None


def _extract_sensor_id(content: str) -> str | None:
    for pattern in _SENSOR_PATTERNS:
        m = pattern.search(content)
        if m:
            return m.group(1)
    return None


class TextParser(BaseParser):
    def parse(self, content: str, guidance: dict | None = None) -> dict[str, Any]:
        extracted: dict[str, Any] = {}

        # ------------------------------------------------------------------
        # 1. Generic key=value extraction (catches most structured text logs)
        # ------------------------------------------------------------------
        for key, value in KV_PATTERN.findall(content):
            extracted[key] = value

        # ------------------------------------------------------------------
        # 2. Timestamp — dedicated multi-pattern extraction
        #    Overrides any "time"-like KV hit because the regex is more precise
        # ------------------------------------------------------------------
        ts = _extract_timestamp(content)
        if ts:
            extracted["timestamp"] = ts

        # ------------------------------------------------------------------
        # 3. Tool ID
        # ------------------------------------------------------------------
        if "tool_id" not in extracted and "tool" not in extracted:
            tool = _extract_tool_id(content)
            if tool:
                extracted["tool_id"] = tool

        # ------------------------------------------------------------------
        # 4. Sensor ID
        # ------------------------------------------------------------------
        if "sensor_id" not in extracted and "sensor" not in extracted:
            sensor = _extract_sensor_id(content)
            if sensor:
                extracted["sensor_id"] = sensor

        # ------------------------------------------------------------------
        # 5. Chamber
        # ------------------------------------------------------------------
        chamber = CHAMBER_PATTERN.search(content)
        if chamber:
            extracted.setdefault("chamber", chamber.group(1))

        # ------------------------------------------------------------------
        # 6. Alarm / error code
        #    Prefer the more specific _ERROR_CODE_PATTERN over bare ALARM_PATTERN
        # ------------------------------------------------------------------
        err_m = _ERROR_CODE_PATTERN.search(content)
        if err_m:
            extracted.setdefault("alarm", err_m.group(1))
        else:
            alarm = ALARM_PATTERN.search(content)
            if alarm:
                extracted.setdefault("alarm", alarm.group(1))

        # ------------------------------------------------------------------
        # 7. Numeric sensor values — only set if not already captured by KV
        # ------------------------------------------------------------------
        if "TEMP" not in extracted and "temperature" not in extracted and "temperature_c" not in extracted:
            temp_m = _TEMP_PATTERN.search(content)
            if temp_m:
                extracted["temperature_c"] = temp_m.group(1)

        if "PRESSURE" not in extracted and "pressure" not in extracted and "pressure_pa" not in extracted:
            press_m = _PRESSURE_PATTERN.search(content)
            if press_m:
                extracted["pressure_pa"] = press_m.group(1)

        # ------------------------------------------------------------------
        # 8. Severity and status
        # ------------------------------------------------------------------
        if "severity" not in extracted:
            sev_m = _SEVERITY_PATTERN.search(content)
            if sev_m:
                extracted["severity"] = sev_m.group(1)

        if "status" not in extracted:
            stat_m = _STATUS_PATTERN.search(content)
            if stat_m:
                extracted["status"] = stat_m.group(1)

        # ------------------------------------------------------------------
        # 9. LLM fallback — only if nothing extracted AND parsing_goal given
        #    (main.py handles all other LLM enrichment)
        # ------------------------------------------------------------------
        if not extracted and guidance and guidance.get("parsing_goal"):
            try:
                from app.llm import parse_unstructured_with_llm
                llm_data = parse_unstructured_with_llm(content, guidance=guidance)
                if llm_data:
                    return {str(k): v for k, v in llm_data.items()}
            except Exception:
                pass

        if not extracted:
            return {"raw_text": content.strip()}

        return extracted