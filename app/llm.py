from __future__ import annotations

import json
import os
from typing import Any


def parse_unstructured_with_llm(text: str) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    prompt = (
        "Extract key fields from this semiconductor tool log as JSON. "
        "Use keys like event_type, error_code, chamber, temp, pressure, severity if present. "
        "Return strict JSON only.\n\n"
        f"Log: {text}"
    )

    response = client.responses.create(
        model=model,
        input=prompt,
        temperature=0,
    )

    output_text = response.output_text.strip()
    try:
        return json.loads(output_text)
    except json.JSONDecodeError:
        return None


def explain_with_llm(payload: dict[str, Any]) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    prompt = (
        "You are a semiconductor equipment engineer assistant. "
        "Explain this normalized event in one concise sentence with likely cause.\n"
        f"Payload: {json.dumps(payload)}"
    )

    response = client.responses.create(model=model, input=prompt, temperature=0.2)
    return response.output_text.strip() or None
