from __future__ import annotations

from typing import Any

from app.llm import explain_with_llm


def explain_event(payload: dict[str, Any]) -> str:
    llm_explanation = explain_with_llm(payload)
    if llm_explanation:
        return llm_explanation

    event = payload.get("event_type", "unknown event")
    chamber = payload.get("chamber_id", "unknown")
    severity = payload.get("severity", "medium")
    temp = payload.get("temperature_c")
    pressure = payload.get("vacuum_pressure")

    clauses = [f"Detected {event} in chamber {chamber} with {severity} severity."]

    if pressure is not None:
        clauses.append(f"Observed vacuum pressure is {pressure}.")
    if temp is not None:
        clauses.append(f"Observed temperature is {temp}C.")

    if event == "vacuum_fault":
        clauses.append("Likely causes include leak, pump degradation, or valve instability.")
    elif event == "thermal_fault":
        clauses.append("Likely causes include cooling inefficiency, sensor drift, or process overload.")
    else:
        clauses.append("Further diagnostic context is recommended.")

    return " ".join(clauses)
