from __future__ import annotations

import json
from typing import Optional


def detect_format(content: str, filename: Optional[str] = None) -> str:
    if filename:
        lower = filename.lower()
        if lower.endswith(".json"):
            return "json"
        if lower.endswith(".xml"):
            return "xml"
        if lower.endswith(".csv"):
            return "csv"
        if lower.endswith(".txt") or lower.endswith(".log"):
            return "text"

    stripped = content.strip()
    if not stripped:
        return "text"

    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
            return "json"
        except json.JSONDecodeError:
            pass

    if stripped.startswith("<") and stripped.endswith(">"):
        if "</" in stripped or "<?xml" in stripped:
            return "xml"

    lines = [line for line in stripped.splitlines() if line.strip()]
    if lines and "," in lines[0] and len(lines[0].split(",")) > 1:
        return "csv"

    return "text"
