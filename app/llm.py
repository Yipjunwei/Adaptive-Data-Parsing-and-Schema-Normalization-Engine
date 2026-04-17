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
    return genai.GenerativeModel("models/gemini-2.5-flash-lite")


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


def parse_unstructured_with_llm(raw_text: str, guidance: dict | None = None) -> dict:
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
You are an AI parser for semiconductor tool logs.

Extract structured information from the raw log below.

Return ONLY valid JSON.
Do not include markdown fences.
Do not explain anything.

Use this schema when possible:
{json.dumps(CANONICAL_FIELDS)}

Rules:
- If a field is not found, omit it.
- Prefer canonical field names.
- Infer event_type if possible.
- Infer severity if possible.
- Keep the most important / primary event if multiple are implied.
{guidance_text}

Raw log:
{raw_text}
"""

    response = model.generate_content(prompt)
    text = _clean_json_text(_extract_text(response))

    if not text:
        raise ValueError("Gemini returned an empty response.")

    return json.loads(text)


def refine_with_llm(
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

You are given:
1. Raw log text
2. Initial extracted payload
3. Initial normalized payload
4. Optional engineer guidance

Your task:
- identify the primary event if multiple events exist
- map unknown or messy fields into canonical fields
- keep only the most relevant structured information
- prefer this canonical schema:
{json.dumps(CANONICAL_FIELDS)}

Return ONLY valid JSON.
Do not include markdown fences.
Do not explain anything.

Rules:
- If multiple events exist, prioritize the most critical event.
- Ignore irrelevant metadata unless useful.
- Preserve true timestamps over counters/uptime values.
- If unsure, keep the most likely interpretation.

{guidance_text}

Raw log:
{raw_text}

Initial raw payload:
{json.dumps(raw_payload, ensure_ascii=False)}

Initial normalized payload:
{json.dumps(normalized_payload, ensure_ascii=False)}
"""

    response = model.generate_content(prompt)
    text = _clean_json_text(_extract_text(response))

    if not text:
        raise ValueError("Gemini returned an empty refinement.")

    return json.loads(text)


def explain_with_llm(payload: dict) -> str:
    model = _get_model()

    prompt = f"""
You are an engineer-friendly AI assistant for semiconductor tool logs.

Given this structured event payload, write a short explanation in plain English.
Keep it concise, clear, and practical.
Mention likely issue and why it matters if possible.

Payload:
{json.dumps(payload, ensure_ascii=False)}
"""

    response = model.generate_content(prompt)
    text = _extract_text(response)

    if not text:
        raise ValueError("Gemini returned an empty explanation.")

    return text