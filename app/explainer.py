from __future__ import annotations

from typing import Any

from app.llm import explain_with_llm

def basic_explanation(payload: dict) -> str:
    event_type = payload.get("event_type", "unknown event")
    severity = payload.get("severity", "unknown severity")
    chamber = payload.get("chamber_id")
    tool = payload.get("tool_id")

    parts = [f"Detected {event_type} with severity {severity}."]
    if chamber is not None:
        parts.append(f"Affected chamber: {chamber}.")
    if tool:
        parts.append(f"Tool: {tool}.")

    return " ".join(parts)

def explain_event(payload: dict) -> str:
    try:
        return explain_with_llm(payload)
    except Exception:
        return basic_explanation(payload)