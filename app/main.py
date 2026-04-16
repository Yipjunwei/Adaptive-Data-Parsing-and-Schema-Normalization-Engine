"""
Adaptive Tool Log Intelligence Pipeline — FastAPI entry point.

Key changes from v0:
  - Vendor profile system: known sources skip Gemini entirely.
  - Single LLM call: parse_and_explain() returns payload + human summary together.
  - human_summary always present in response.
  - /profiles endpoint exposes learned vendor profiles.
  - /demo endpoint runs all synthetic test logs for the demo story.
"""
from __future__ import annotations

import json
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
from app.llm import explain_payload, parse_and_explain, refine_payload
from app.memory import learn_from_ingestion, recall_event
from app.models import FeedbackRule
from app.parser import parse_content
from app.profiles import init_profiles, list_profiles, lookup_profile, promote_profile
from app.schema_mapper import normalize_payload

app = FastAPI(
    title="Adaptive Tool Log Intelligence Pipeline",
    version="0.2.0",
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
    return {"message": "Adaptive Tool Log Intelligence Pipeline v0.2.0 is running."}


# ---------------------------------------------------------------------------
# Core ingestion
# ---------------------------------------------------------------------------
@app.post("/upload-log")
async def upload_log(
    file: UploadFile | None = File(None),
    raw_text: str | None = Form(None),
    fields_of_interest: str | None = Form(None),
    focus_section: str | None = Form(None),
    parsing_goal: str | None = Form(None),
    vendor_label: str | None = Form(None),
) -> dict:

    if file is None and (raw_text is None or not raw_text.strip()):
        raise HTTPException(status_code=400, detail="Provide either 'file' or non-empty 'raw_text'.")

    # -------------------------
    # Read content
    # -------------------------
    if file is not None:
        content = (await file.read()).decode("utf-8", errors="ignore")
        filename = file.filename
    else:
        content = raw_text or ""
        filename = None

    guidance = {
        "fields_of_interest": fields_of_interest or None,
        "focus_section": focus_section or None,
        "parsing_goal": parsing_goal or None,
    }

    detected_format = detect_format(content, filename)

    # -------------------------
    # STEP 1: Rule-based parsing
    # -------------------------
    raw_payload = parse_content(content, detected_format, guidance=guidance)

    rules = get_promoted_memory_rules() | get_schema_rules()
    normalized_payload, confidence = normalize_payload(raw_payload, rules, raw_text=content)

    # -------------------------
    # STEP 2: Profile lookup
    # -------------------------
    profile = lookup_profile(detected_format, raw_payload)

    llm_used = False
    human_summary = ""

    if profile:
        # Apply learned key mapping
        for raw_k, canonical_k in profile.key_map.items():
            if raw_k in raw_payload:
                normalized_payload[canonical_k] = raw_payload[raw_k]

        # Use preferred event type if model unsure
        if normalized_payload.get("event_type") == "unknown_event" and profile.preferred_event_type:
            normalized_payload["event_type"] = profile.preferred_event_type

        confidence = min(1.0, round(confidence + 0.12, 3))
        source_status = "known_profile"

    else:
        # -------------------------
        # STEP 3: Gemini parsing
        # -------------------------
        llm_result = parse_and_explain(content, guidance=guidance)

        llm_used = True
        llm_payload = llm_result.get("payload", {})
        human_summary = llm_result.get("summary", "")

        # Merge LLM results
        for k, v in llm_payload.items():
            if k not in normalized_payload or normalized_payload[k] is None:
                normalized_payload[k] = v

        _, new_conf = normalize_payload(llm_payload, rules, raw_text=content)
        confidence = max(confidence, min(0.95, new_conf + 0.05))

        source_status = "new_source"

    # -------------------------
    # STEP 4: Refinement (smarter trigger)
    # -------------------------
    should_refine = (
        confidence < 0.65
        or normalized_payload.get("event_type") == "unknown_event"
        or guidance.get("fields_of_interest")
        or any(len(str(k).split("_")) >= 3 for k in raw_payload.keys())
    )

    if should_refine:
        try:
            refined = refine_payload(content, raw_payload, normalized_payload, guidance)
            if refined:
                for k, v in refined.items():
                    normalized_payload[k] = v

                _, refined_conf = normalize_payload(refined, rules, raw_text=content)
                confidence = max(confidence, min(0.95, refined_conf + 0.05))
        except Exception:
            pass

    # -------------------------
    # STEP 5: Memory fallback
    # -------------------------
    if normalized_payload.get("event_type") == "unknown_event":
        remembered = recall_event(content)
        if remembered:
            normalized_payload["event_type"] = remembered
            confidence = min(1.0, round(confidence + 0.08, 3))

    # -------------------------
    # STEP 6: Explanation fallback
    # -------------------------
    if not human_summary:
        human_summary = explain_payload(normalized_payload)

    # -------------------------
    # STEP 7: Learn & promote profile
    # -------------------------
    learn_from_ingestion(raw_payload, normalized_payload, content)

    promote_profile(
        format_detected=detected_format,
        raw_payload=raw_payload,
        normalized_payload=normalized_payload,
        confidence=confidence,
        used_gemini=llm_used,
        summary=human_summary,
        focus_section=guidance.get("focus_section"),
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
        "vendor_profile": profile.profile_id if profile else None,
        "llm_used": llm_used,
        "guidance": guidance,
        "raw_payload": raw_payload,
        "normalized_payload": normalized_payload,
        "human_summary": human_summary,
        "confidence": confidence,
        "needs_review": needs_review,
    }


# ---------------------------------------------------------------------------
# Demo endpoint — runs all synthetic logs for the presentation story
# ---------------------------------------------------------------------------

root_dir = Path(__file__).parent.parent
candidate_a = root_dir / "synthetic_logs"
candidate_b = root_dir / "data" / "synthetic_logs"

if candidate_a.exists():
    SYNTHETIC_LOG_DIR = candidate_a
else:
    SYNTHETIC_LOG_DIR = candidate_b


@app.get("/demo")
def demo() -> dict:
    """
    Runs all synthetic logs through the pipeline and returns side-by-side results.
    This powers the 'same event, 3 vendors, 1 schema' demo story.
    """
    results = []
    logs = [
        ("vendor_a_dry_etch.json", "Vendor A — JSON"),
        ("vendor_b_dry_etch.json", "Vendor B — JSON"),
        ("sensor_trace.csv",       "Sensor trace — CSV"),
        ("event_log.txt",          "Event log — plain text"),
        ("recipe_log.xml",         "Recipe log — XML"),
    ]

    for filename, label in logs:
        path = SYNTHETIC_LOG_DIR / filename
        if not path.exists():
            results.append({"label": label, "error": "file not found"})
            continue

        content = path.read_text(encoding="utf-8")
        fmt = detect_format(content, filename)
        raw_payload = parse_content(content, fmt)

        rules = get_promoted_memory_rules() | get_schema_rules()
        normalized, confidence = normalize_payload(raw_payload, rules, raw_text=content)

        profile = lookup_profile(fmt, raw_payload)
        if not profile:
            llm_result = parse_and_explain(content)
            llm_payload = llm_result.get("payload", {})
            summary = llm_result.get("summary", "")
            for k, v in llm_payload.items():
                if k not in normalized:
                    normalized[k] = v
            promote_profile(fmt, raw_payload, normalized, confidence, label=label)
        else:
            summary = explain_payload(normalized)

        results.append(
            {
                "label": label,
                "format": fmt,
                "source_status": "known" if profile else "new",
                "normalized_payload": normalized,
                "human_summary": summary,
                "confidence": confidence,
            }
        )

    return {"demo_scenario": "Vacuum fault — chamber C1 — ETCH_TOOL_42", "results": results}


# ---------------------------------------------------------------------------
# Standard endpoints (unchanged from v0)
# ---------------------------------------------------------------------------

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


@app.get("/profiles")
def profiles() -> dict:
    return {"vendor_profiles": list_profiles()}


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
