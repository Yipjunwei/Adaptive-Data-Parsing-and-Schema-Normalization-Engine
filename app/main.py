"""
Adaptive Tool Log Intelligence Pipeline — FastAPI entry point.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

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
from app.llm import explain_payload, parse_and_explain
from app.memory import learn_from_ingestion, recall_event
from app.models import FeedbackRule
from app.parser import parse_content
from app.profiles import (
    init_profiles,
    list_profiles,
    lookup_profile,
    promote_profile,
    build_profile_guidance,
)
from app.schema_mapper import assess_payload, normalize_payload

app = FastAPI(
    title="Adaptive Tool Log Intelligence Pipeline",
    version="0.3.0",
    description=(
        "Ingest semiconductor tool logs, detect format, parse payloads, "
        "normalize schema, generate engineer-friendly explanations, "
        "and learn vendor profiles over time."
    ),
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    init_profiles()


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Adaptive Tool Log Intelligence Pipeline v0.3.0 is running."}


def _decode_upload(file_bytes: bytes, filename: str | None) -> tuple[str | bytes, str, str | None]:
    """
    Returns:
      content_for_parser: str | bytes
      raw_text_for_llm: str
      detected_format: str
    """
    detected_format = detect_format("", filename)

    if detected_format == "bin":
        content_for_parser = file_bytes
        raw_text_for_llm = file_bytes.hex()  # safe text fallback for downstream components
    else:
        text = file_bytes.decode("utf-8", errors="ignore")
        content_for_parser = text
        raw_text_for_llm = text

    return content_for_parser, raw_text_for_llm, detected_format


@app.post("/upload-log")
async def upload_log(
    file: UploadFile | None = File(None),
    raw_text: str | None = Form(None),
    fields_of_interest: str | None = Form(None),
    focus_section: str | None = Form(None),
    parsing_goal: str | None = Form(None),
    vendor_label: str | None = Form(None),
) -> dict[str, Any]:
    if file is None and (raw_text is None or not raw_text.strip()):
        raise HTTPException(status_code=400, detail="Provide either 'file' or non-empty 'raw_text'.")

    # ------------------------------------------------------------------
    # 1. Read content safely
    # ------------------------------------------------------------------
    if file is not None:
        file_bytes = await file.read()
        filename = file.filename
        content, raw_text_for_llm, detected_format = _decode_upload(file_bytes, filename)
    else:
        filename = None
        raw_text_for_llm = raw_text or ""
        content = raw_text_for_llm
        detected_format = detect_format(raw_text_for_llm, filename)

    # ------------------------------------------------------------------
    # 2. Base guidance
    # ------------------------------------------------------------------
    guidance: dict[str, Any] = {
        "fields_of_interest": fields_of_interest or None,
        "focus_section": focus_section or None,
        "parsing_goal": parsing_goal or None,
        "vendor_label": vendor_label or None,
    }

    rules = get_promoted_memory_rules() | get_schema_rules()
    llm_used = False
    human_summary = ""
    source_status = "new_source"

    # ------------------------------------------------------------------
    # 3. Initial raw parse (no LLM — pure structural extraction)
    # ------------------------------------------------------------------
    raw_payload = parse_content(content, detected_format, guidance=None)

    # ------------------------------------------------------------------
    # 4. Look up vendor/source profile
    # ------------------------------------------------------------------
    profile = lookup_profile(
        format_detected=detected_format,
        raw_payload=raw_payload,
        vendor_label=vendor_label,
    )

    # ------------------------------------------------------------------
    # 5. Re-parse with profile guidance if a known profile was found
    # ------------------------------------------------------------------
    if profile:
        profile_guidance = build_profile_guidance(profile)
        merged_guidance = {**guidance, **profile_guidance}
        reparsed = parse_content(content, detected_format, guidance=merged_guidance)
        if reparsed:
            raw_payload = reparsed
        source_status = "known_profile"

    # ------------------------------------------------------------------
    # 6. Normalize (rules + alias mapping + event/severity inference)
    # ------------------------------------------------------------------
    normalized_payload, confidence, assessment = normalize_payload(
        raw_payload,
        rules,
        raw_text=raw_text_for_llm,
    )

    # ------------------------------------------------------------------
    # 7. Apply profile enrichments (key map + event hint + confidence boost)
    # ------------------------------------------------------------------
    if profile:
        for raw_k, canonical_k in profile.key_map.items():
            if raw_k in raw_payload and canonical_k not in normalized_payload:
                normalized_payload[canonical_k] = raw_payload[raw_k]

        if normalized_payload.get("event_type") == "unknown_event" and profile.preferred_event_type:
            normalized_payload["event_type"] = profile.preferred_event_type

        human_summary = profile.last_summary or ""

        profile_bonus = min(0.1, round((profile.confidence_avg or 0.0) * 0.08, 3))
        assessment = assess_payload(
            raw_payload=raw_payload,
            normalized_payload=normalized_payload,
            raw_text=raw_text_for_llm,
            profile_reliability_bonus=profile_bonus,
        )
        confidence = assessment["confidence"]

    # ------------------------------------------------------------------
    # 8. LLM enrichment — only for unknown sources or genuinely low confidence
    #    (at most ONE Gemini call per request)
    # ------------------------------------------------------------------
    llm_reasons: list[str] = []
    if not profile:
        llm_reasons.append("new_source")
    if normalized_payload.get("event_type") == "unknown_event":
        llm_reasons.append("unknown_event")
    if assessment["signals"].get("missing_critical_fields"):
        llm_reasons.append("missing_critical_fields")
    if assessment["signals"].get("has_consistency_issues"):
        llm_reasons.append("consistency_issue")
    if assessment["signals"].get("ambiguous_event"):
        llm_reasons.append("ambiguous_event")
    if assessment["signals"].get("sparse_parse"):
        llm_reasons.append("sparse_parse")
    if bool(guidance.get("fields_of_interest")) or bool(guidance.get("parsing_goal")):
        llm_reasons.append("user_guidance")

    needs_llm = bool(llm_reasons)

    if needs_llm:
        try:
            llm_result = parse_and_explain(
                raw_text=raw_text_for_llm,
                guidance=guidance,
                initial_payload=raw_payload,
                detected_format=detected_format,
            )
            llm_used = True
            llm_payload = llm_result.get("payload", {})
            llm_summary = llm_result.get("summary", "")

            # Merge LLM fields — only fill gaps, never overwrite good values
            for k, v in llm_payload.items():
                if v is not None and (k not in normalized_payload or normalized_payload[k] is None):
                    normalized_payload[k] = v

            if llm_summary and not human_summary:
                human_summary = llm_summary

            merged_payload = dict(normalized_payload)
            for k, v in llm_payload.items():
                if v is not None and (k not in merged_payload or merged_payload[k] is None):
                    merged_payload[k] = v

            normalized_payload = merged_payload
            profile_bonus = 0.0
            if profile:
                profile_bonus = min(0.1, round((profile.confidence_avg or 0.0) * 0.08, 3))

            assessment = assess_payload(
                raw_payload=raw_payload,
                normalized_payload=normalized_payload,
                raw_text=raw_text_for_llm,
                profile_reliability_bonus=profile_bonus,
            )
            confidence = min(0.95, assessment["confidence"])
        except Exception:
            pass  # LLM failure is non-fatal; pipeline continues with what we have

    # ------------------------------------------------------------------
    # 9. Memory fallback for event_type
    # ------------------------------------------------------------------
    if normalized_payload.get("event_type") == "unknown_event":
        remembered = recall_event(raw_text_for_llm)
        if remembered:
            normalized_payload["event_type"] = remembered
            assessment = assess_payload(
                raw_payload=raw_payload,
                normalized_payload=normalized_payload,
                raw_text=raw_text_for_llm,
                profile_reliability_bonus=min(0.1, round((profile.confidence_avg or 0.0) * 0.08, 3)) if profile else 0.0,
            )
            confidence = assessment["confidence"]

    # ------------------------------------------------------------------
    # 10. Generate explanation — only if LLM wasn't already used above
    # ------------------------------------------------------------------
    if not human_summary:
        if llm_used:
            # LLM was called but returned no summary — use basic fallback (no extra call)
            from app.explainer import basic_explanation
            human_summary = basic_explanation(normalized_payload)
        else:
            # Profile hit but no cached summary — generate once and it will be cached on promote
            try:
                human_summary = explain_payload(normalized_payload)
            except Exception:
                from app.explainer import basic_explanation
                human_summary = basic_explanation(normalized_payload)

    # ------------------------------------------------------------------
    # 11. Learn from ingestion
    # ------------------------------------------------------------------
    learn_from_ingestion(raw_payload, normalized_payload, raw_text_for_llm)

    promoted = promote_profile(
        format_detected=detected_format,
        raw_payload=raw_payload,
        normalized_payload=normalized_payload,
        confidence=confidence,
        used_gemini=llm_used,
        summary=human_summary,
        focus_section=guidance.get("focus_section"),
        vendor_label=vendor_label,
    )

    needs_review = confidence < 0.6

    log_id = store_log(
        format_detected=detected_format,
        confidence=confidence,
        needs_review=needs_review,
        payload=normalized_payload,
        explanation=human_summary,
    )

    return {
        "log_id": log_id,
        "format_detected": detected_format,
        "source_status": source_status,
        "vendor_profile": profile.profile_id if profile else (promoted.profile_id if promoted else None),
        "llm_used": llm_used,
        "guidance": guidance,
        "raw_payload": raw_payload,
        "normalized_payload": normalized_payload,
        "human_summary": human_summary,
        "confidence": confidence,
        "confidence_breakdown": assessment.get("confidence_breakdown", {}),
        "validation_scores": assessment.get("validation_scores", {}),
        "missing_critical_fields": assessment.get("missing_critical_fields", []),
        "consistency_issues": assessment.get("consistency_issues", []),
        "llm_reasons": llm_reasons,
        "needs_review": needs_review,
    }




# ---------------------------------------------------------------------------
# Standard endpoints
# ---------------------------------------------------------------------------

@app.get("/logs")
def list_logs(limit: int = 100) -> dict[str, Any]:
    return {"items": fetch_logs(limit=limit)}


@app.get("/logs/{log_id}")
def get_log(log_id: int) -> dict[str, Any]:
    row = fetch_log(log_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Log not found")
    return row


@app.post("/feedback")
def submit_feedback(rule: FeedbackRule) -> dict[str, str]:
    upsert_schema_rule(rule.raw_key, rule.canonical_key)
    return {"status": "ok", "message": "Schema mapping rule saved."}


@app.get("/schema-rules")
def schema_rules() -> dict[str, Any]:
    return {
        "manual_rules": get_schema_rules(),
        "memory_promoted_rules": get_promoted_memory_rules(),
    }


@app.get("/profiles")
def profiles() -> dict[str, Any]:
    return {"vendor_profiles": list_profiles()}


@app.get("/memory")
def memory(limit: int = 50) -> dict[str, Any]:
    return get_memory_snapshot(limit=limit)


@app.get("/stats")
def stats() -> dict[str, Any]:
    return get_stats()


@app.get("/anomaly-check")
def anomaly_check() -> dict[str, Any]:
    logs = fetch_logs(limit=500)
    return anomaly_score(logs)