from __future__ import annotations

import re
from typing import Any

from app.parsers.base import BaseParser

KV_PATTERN = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*=\s*([\w\.-]+)")
CHAMBER_PATTERN = re.compile(r"chamber\s*([0-9]+|[A-Za-z])", re.IGNORECASE)
ALARM_PATTERN = re.compile(r"alarm\s*([0-9]+)", re.IGNORECASE)


class TextParser(BaseParser):
    def parse(self, content: str, guidance: dict | None = None) -> dict[str, Any]:
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

        # Only fall back to LLM if nothing at all was extracted AND
        # an explicit parsing_goal was provided in guidance.
        # The main pipeline (main.py) handles all other LLM enrichment.
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