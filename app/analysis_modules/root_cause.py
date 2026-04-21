from __future__ import annotations

import json
from typing import Any

from app.llm import _extract_text, _get_model


def heuristic_root_cause(payload: dict[str, Any], latest_context: str | None = None) -> dict[str, str]:
    event_type = str(payload.get("event_type", "unknown_event")).lower().strip()
    tool_id = payload.get("tool_id", "unknown tool")
    chamber = payload.get("chamber_id", "unknown chamber")
    pressure = payload.get("pressure_pa")
    temp = payload.get("temperature_c")
    sensor_id = payload.get("sensor_id")
    status = payload.get("status")

    cause = "Insufficient evidence to isolate a single root cause. Review the latest log context and sensor trends."
    action = "Inspect the affected chamber, verify sensors, and correlate with the previous few events before resuming the run."

    if event_type == "vacuum_fault":
        cause = f"Chamber pressure is abnormally low or unstable ({pressure} Pa), suggesting a pump, valve seal, or chamber leak issue."
        action = f"Check turbo/roughing pump health, gate valve seal, and chamber leak integrity on {tool_id} chamber {chamber}."
    elif event_type == "thermal_fault":
        cause = f"Temperature is above the safe operating band ({temp} C), which may indicate heater runaway, cooling failure, or poor thermal contact."
        action = f"Inspect heater control loop, cooling path, and wafer/chuck contact on {tool_id} chamber {chamber}."
    elif event_type == "rf_power_fault":
        cause = "Repeated RF or plasma faults suggest unstable matching, reflected power issues, or degrading RF hardware."
        action = f"Check match network tuning, reflected power trend, RF cables, and generator stability on {tool_id}."
    elif event_type == "gas_flow_fault":
        cause = "Gas flow or MFC behavior appears outside the expected range, pointing to MFC drift, blocked line, or supply instability."
        action = f"Verify gas line pressure, MFC calibration, and purge path integrity on {tool_id}."
    elif event_type == "sensor_fault":
        cause = f"Sensor-related readings indicate loss of signal, out-of-range values, or calibration drift{' on ' + str(sensor_id) if sensor_id else ''}."
        action = "Inspect the affected sensor, wiring, and calibration status. Replace or recalibrate if the issue repeats."
    elif event_type == "wafer_handling_fault":
        cause = "Wafer handling alarms point to robot alignment, chuck vacuum, or slot/FOUP transfer problems."
        action = "Inspect robot arm alignment, wafer presence sensing, and chuck vacuum before restarting automation."
    elif event_type == "chamber_fault":
        cause = f"Chamber isolation or interlock conditions suggest valve, seal, venting, or pumping state mismatch{f' ({status})' if status else ''}."
        action = f"Inspect gate valves, vent/pump sequence, and interlock logic on {tool_id} chamber {chamber}."
    elif event_type == "recipe_violation":
        cause = "Process setpoints or recipe execution drifted from the expected operating envelope."
        action = "Review the active recipe, compare the failing step against the golden baseline, and confirm setpoint propagation."

    if latest_context:
        action = f"{action} Context: {latest_context[:180]}"

    return {
        "most_likely_cause": cause,
        "suggested_action": action,
    }


def suggest_root_cause(payload: dict[str, Any], latest_context: str | None = None, use_llm: bool = True) -> dict[str, str]:
    fallback = heuristic_root_cause(payload, latest_context=latest_context)
    if not use_llm:
        return fallback

    try:
        model = _get_model()
        prompt = f'''
You are assisting with semiconductor equipment health diagnostics.
Return ONLY valid JSON with this schema:
{{
  "most_likely_cause": "...",
  "suggested_action": "..."
}}

Be concise and practical.
Ground the answer in the payload.
Do not invent unavailable measurements.
If uncertain, state the most plausible cause and mention what to inspect.

Payload:
{json.dumps(payload, ensure_ascii=False)}

Latest context:
{latest_context or ""}
'''
        response = model.generate_content(prompt)
        text = _extract_text(response)
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        if isinstance(parsed, dict) and parsed.get("most_likely_cause") and parsed.get("suggested_action"):
            return {
                "most_likely_cause": str(parsed["most_likely_cause"]),
                "suggested_action": str(parsed["suggested_action"]),
            }
    except Exception:
        pass
    return fallback
