from __future__ import annotations

import json
import os
from typing import Any

import google.generativeai as genai

CANONICAL_FIELDS = [
    "timestamp",
    "tool_id",
    "chamber_id",
    "temperature_c",
    "pressure_pa",
    "error_code",
    "severity",
    "raw_message",
    "event_type",
    "sensor_id",
    "status",
]


def _get_model():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    genai.configure(api_key=api_key)
    
    # return genai.GenerativeModel("gemini-2.5-flash-lite") // 2.5 got limit 20 requests per day
    return genai.GenerativeModel("gemini-3.1-flash-lite-preview")


def _extract_text(response: Any) -> str:
    if hasattr(response, "text") and response.text:
        return response.text.strip()

    try:
        parts = response.candidates[0].content.parts
        return "".join(getattr(part, "text", "") for part in parts).strip()
    except Exception:
        return ""


def _clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()
    return text


def parse_and_explain(
    raw_text: str,
    guidance: dict | None = None,
    initial_payload: dict | None = None,
    detected_format: str | None = None,
) -> dict:
    model = _get_model()

    guidance_text = ""
    if guidance:
        guidance_text = f"""
Guidance:
- fields_of_interest: {guidance.get("fields_of_interest")}
- focus_section: {guidance.get("focus_section")}
- parsing_goal: {guidance.get("parsing_goal")}
"""

    initial_payload_text = json.dumps(initial_payload or {}, ensure_ascii=False)

    prompt = f"""
You are an AI parser for semiconductor tool logs.

Your task:
1. extract the most important structured information from the log
2. if multiple events exist, choose the primary event
3. provide a short engineer-friendly summary

Return ONLY valid JSON with this shape:
{{
  "payload": {{
    "timestamp": "...",
    "tool_id": "...",
    "chamber_id": 0,
    "temperature_c": 0,
    "pressure_pa": 0,
    "error_code": "...",
    "severity": "...",
    "raw_message": "...",
    "event_type": "...",
    "sensor_id": "...",
    "status": "..."
  }},
  "summary": "short explanation"
}}

Rules:
- Use canonical field names where possible.
- Omit fields that cannot be inferred.
- Prioritize the most critical event if there are multiple events.
- Ignore irrelevant metadata unless useful.
- Preserve real timestamps over counters/uptime values.
- Return only JSON, no markdown, no commentary.

Format detected: {detected_format}
{guidance_text}

Initial extracted payload:
{initial_payload_text}

Raw log:
{raw_text}
"""

    response = model.generate_content(prompt)
    text = _clean_json_text(_extract_text(response))

    if not text:
        raise ValueError("Gemini returned empty parse_and_explain response.")

    return json.loads(text)


def refine_payload(
    raw_text: str,
    raw_payload: dict,
    normalized_payload: dict,
    guidance: dict | None = None,
) -> dict:
    model = _get_model()

    guidance_text = ""
    if guidance:
        guidance_text = f"""
Guidance:
- fields_of_interest: {guidance.get("fields_of_interest")}
- focus_section: {guidance.get("focus_section")}
- parsing_goal: {guidance.get("parsing_goal")}
"""

    prompt = f"""
You are refining a parsed semiconductor tool log.

Return ONLY valid JSON.
Do not explain anything.

Use only these canonical fields where possible:
{json.dumps(CANONICAL_FIELDS)}

Rules:
- Keep the primary event only.
- Improve field mapping from ambiguous keys.
- Ignore irrelevant metadata.
- Preserve true timestamps over uptime/counters.
- Use guidance if provided.

{guidance_text}

Raw log:
{raw_text}

Raw payload:
{json.dumps(raw_payload, ensure_ascii=False)}

Current normalized payload:
{json.dumps(normalized_payload, ensure_ascii=False)}
"""

    response = model.generate_content(prompt)
    text = _clean_json_text(_extract_text(response))

    if not text:
        raise ValueError("Gemini returned empty refine_payload response.")

    return json.loads(text)


def explain_payload(payload: dict) -> str:
    model = _get_model()

    prompt = f"""
You are an engineer-friendly AI assistant for semiconductor tool logs.

Given this structured payload, write a short explanation in plain English.
Be concise, practical, and mention likely issue and impact if possible.

Payload:
{json.dumps(payload, ensure_ascii=False)}
"""

    response = model.generate_content(prompt)
    text = _extract_text(response)

    if not text:
        raise ValueError("Gemini returned empty explanation.")

    return text


# compatibility helpers for older modules
def parse_unstructured_with_llm(raw_text: str, guidance: dict | None = None) -> dict:
    result = parse_and_explain(raw_text=raw_text, guidance=guidance)
    if isinstance(result, dict) and isinstance(result.get("payload"), dict):
        return result["payload"]
    return {}


def explain_with_llm(payload: dict) -> str:
    return explain_payload(payload)