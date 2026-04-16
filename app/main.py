from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.anomaly import anomaly_score
from app.db import (
    fetch_log,
    fetch_logs,
    get_memory_snapshot,
    get_promoted_memory_rules,
    get_schema_rules,
    get_stats,
    init_db,
    store_log,
    upsert_schema_rule,
)
from app.detector import detect_format
from app.explainer import explain_event
from app.memory import learn_from_ingestion, recall_event
from app.models import FeedbackRule
from app.parser import parse_content
from app.schema_mapper import normalize_payload

app = FastAPI(
    title="Adaptive Tool Log Intelligence Pipeline",
    version="0.1.0",
    description=(
        "Ingest semiconductor tool logs, detect format, parse payloads, "
        "normalize schema, and generate engineer-friendly explanations."
    ),
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Adaptive Tool Log Intelligence Pipeline is running."}


@app.post("/upload-log")
async def upload_log(
    file: UploadFile | None = File(None),
    raw_text: str | None = Form(None),
    fields_of_interest: str | None = Form(None),
    focus_section: str | None = Form(None),
    parsing_goal: str | None = Form(None),
) -> dict:
    if file is None and (raw_text is None or not raw_text.strip()):
        raise HTTPException(status_code=400, detail="Provide either 'file' or non-empty 'raw_text'.")

    if file is not None:
        content = (await file.read()).decode("utf-8", errors="ignore")
        filename = file.filename
    else:
        content = raw_text or ""
        filename = None

    guidance = {
        "fields_of_interest": fields_of_interest,
        "focus_section": focus_section,
        "parsing_goal": parsing_goal,
    }

    detected_format = detect_format(content, filename)
    raw_payload = parse_content(content, detected_format, guidance=guidance)

    memory_rules = get_promoted_memory_rules()
    user_rules = get_schema_rules()
    rules = memory_rules | user_rules

    normalized_payload, confidence = normalize_payload(raw_payload, rules, raw_text=content)

    should_refine = (
        confidence < 0.65
        or normalized_payload.get("event_type") == "unknown_event"
        or guidance.get("fields_of_interest")
        or guidance.get("focus_section")
        or guidance.get("parsing_goal")
        or any("_" in str(k) and len(str(k).split("_")) >= 3 for k in raw_payload.keys())
    )

    if should_refine:
        try:
            from app.llm import refine_with_llm

            refined_payload = refine_with_llm(
                raw_text=content,
                raw_payload=raw_payload,
                normalized_payload=normalized_payload,
                guidance=guidance,
            )

            if isinstance(refined_payload, dict) and refined_payload:
                normalized_payload, refined_confidence = normalize_payload(
                    refined_payload,
                    rules,
                    raw_text=content,
                )
                confidence = max(confidence, min(0.95, refined_confidence + 0.1))
        except Exception as e:
            print(f"Gemini refinement failed: {e}")
        
    if normalized_payload.get("event_type") == "unknown_event":
        remembered_event = recall_event(content)
        if remembered_event:
            normalized_payload["event_type"] = remembered_event
            confidence = min(1.0, round(confidence + 0.08, 3))

    learn_from_ingestion(raw_payload, normalized_payload, content)

    needs_review = confidence < 0.6
    explanation = explain_event(normalized_payload)

    log_id = store_log(
        format_detected=detected_format,
        confidence=confidence,
        needs_review=needs_review,
        payload=normalized_payload,
        explanation=explanation,
    )

    return {
        "log_id": log_id,
        "format_detected": detected_format,
        "guidance": guidance,
        "raw_payload": raw_payload,
        "normalized_payload": normalized_payload,
        "confidence": confidence,
        "needs_review": needs_review,
        "explanation": explanation,
    }


@app.get("/logs")
def list_logs(limit: int = 100) -> dict:
    return {"items": fetch_logs(limit=limit)}


@app.get("/logs/{log_id}")
def get_log(log_id: int) -> dict:
    row = fetch_log(log_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Log not found")
    return row


@app.post("/feedback")
def submit_feedback(rule: FeedbackRule) -> dict[str, str]:
    upsert_schema_rule(rule.raw_key, rule.canonical_key)
    return {"status": "ok", "message": "Schema mapping rule saved."}


@app.get("/schema-rules")
def schema_rules() -> dict:
    return {
        "manual_rules": get_schema_rules(),
        "memory_promoted_rules": get_promoted_memory_rules(),
    }


@app.get("/memory")
def memory(limit: int = 50) -> dict:
    return get_memory_snapshot(limit=limit)


@app.get("/stats")
def stats() -> dict:
    return get_stats()


@app.get("/anomaly-check")
def anomaly_check() -> dict:
    logs = fetch_logs(limit=500)
    return anomaly_score(logs)
