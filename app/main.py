"""
Adaptive Tool Log Intelligence Pipeline — FastAPI entry point.
Updated with equipment dashboard helpers and PDF report generation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

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
from app.analysis_modules.health import build_fault_timeline, compute_health_summary, filter_logs_for_tool
from app.llm import explain_payload, parse_and_explain
from app.memory import learn_from_ingestion, recall_event
from app.models import FeedbackRule
from app.parser import parse_content
from app.profiles import (
    build_profile_guidance,
    init_profiles,
    list_profiles,
    lookup_profile,
    promote_profile,
)
from app.analysis_modules.reporting import build_health_report_pdf
from app.analysis_modules.root_cause import suggest_root_cause
from app.schema_mapper import assess_payload, normalize_payload

app = FastAPI(
    title="Adaptive Tool Log Intelligence Pipeline",
    version="0.4.0",
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
    return {"message": "Adaptive Tool Log Intelligence Pipeline v0.4.0 is running."}


def _decode_upload(file_bytes: bytes, filename: str | None) -> tuple[str | bytes, str, str | None]:
    detected_format = detect_format("", filename)

    if detected_format == "bin":
        content_for_parser = file_bytes
        raw_text_for_llm = file_bytes.hex()
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

    if file is not None:
        file_bytes = await file.read()
        filename = file.filename
        content, raw_text_for_llm, detected_format = _decode_upload(file_bytes, filename)
    else:
        filename = None
        raw_text_for_llm = raw_text or ""
        content = raw_text_for_llm
        detected_format = detect_format(raw_text_for_llm, filename)

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

    raw_payload = parse_content(content, detected_format, guidance=None)

    profile = lookup_profile(
        format_detected=detected_format,
        raw_payload=raw_payload,
        vendor_label=vendor_label,
    )

    if profile:
        profile_guidance = build_profile_guidance(profile)
        merged_guidance = {**guidance, **profile_guidance}
        reparsed = parse_content(content, detected_format, guidance=merged_guidance)
        if reparsed:
            raw_payload = reparsed
        source_status = "known_profile"

    normalized_payload, confidence, assessment = normalize_payload(
        raw_payload,
        rules,
        raw_text=raw_text_for_llm,
    )

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
            pass

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

    if not human_summary:
        from app.explainer import basic_explanation
        human_summary = basic_explanation(normalized_payload)

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
        "needs_review": needs_review
    }


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


@app.get("/dashboard/summary")
def dashboard_summary(tool_id: str, limit: int = 500) -> dict[str, Any]:
    logs = fetch_logs(limit=limit)
    tool_logs = filter_logs_for_tool(logs, tool_id)
    if not tool_logs:
        raise HTTPException(status_code=404, detail=f"No logs found for tool '{tool_id}'")

    summary = compute_health_summary(tool_logs)
    timeline = build_fault_timeline(tool_logs)
    latest_payload = (summary.get("latest_event") or {}).get("payload", {})
    root_cause = suggest_root_cause(latest_payload, latest_context=(summary.get("latest_event") or {}).get("explanation"), use_llm=True)

    return {
        "tool_id": tool_id,
        "summary": summary,
        "timeline": timeline,
        "latest_payload": latest_payload,
        "root_cause": root_cause,
    }


@app.get("/tools")
def list_tools(limit: int = 500) -> dict[str, Any]:
    logs = fetch_logs(limit=limit)
    tools = sorted({str((log.get("payload", {}) or {}).get("tool_id", "")).strip() for log in logs if (log.get("payload", {}) or {}).get("tool_id")})
    return {"items": tools}


@app.get("/reports/tool-health")
def download_tool_health_report(tool_id: str, limit: int = 500) -> FileResponse:
    logs = fetch_logs(limit=limit)
    tool_logs = filter_logs_for_tool(logs, tool_id)
    if not tool_logs:
        raise HTTPException(status_code=404, detail=f"No logs found for tool '{tool_id}'")

    summary = compute_health_summary(tool_logs)
    latest_event = summary.get("latest_event") or {}
    payload = latest_event.get("payload", {})

    root_cause = suggest_root_cause(payload)   # LLM only here if needed

    pdf_bytes = build_health_report_pdf(
        tool_id=tool_id,
        summary=summary,
        latest_payload=payload,
        root_cause=root_cause,
    )

    out_dir = Path("generated_reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"tool_health_{tool_id}.pdf"
    out_path.write_bytes(pdf_bytes)

    return FileResponse(
        path=str(out_path),
        media_type="application/pdf",
        filename=out_path.name,
    )
