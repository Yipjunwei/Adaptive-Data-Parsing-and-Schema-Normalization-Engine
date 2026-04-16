"""
Adaptive Tool Log Intelligence Pipeline — Streamlit UI v0.2
"""
from __future__ import annotations

import json

import requests
import streamlit as st

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="Tool Log Intelligence",
    layout="wide",
    page_icon="⚙️",
)

st.title("⚙️ Adaptive Tool Log Intelligence Pipeline")

tab_upload, tab_demo, tab_logs, tab_profiles, tab_feedback = st.tabs(
    ["Upload Log", "Demo Mode", "Recent Logs", "Vendor Profiles", "Schema Feedback"]
)


# ─────────────────────────────────────────────
# Tab 1: Upload & parse a log
# ─────────────────────────────────────────────
with tab_upload:
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Input")
        uploaded = st.file_uploader(
            "Upload log file",
            type=["txt", "log", "json", "xml", "csv"],
        )
        pasted = st.text_area(
            "Or paste raw log text",
            height=200,
            placeholder="Paste raw tool log here...",
        )

        with st.expander("Optional parsing guidance"):
            fields_of_interest = st.text_input(
                "Fields of interest",
                placeholder="e.g. temperature_c, pressure_pa, chamber_id",
            )
            focus_section = st.selectbox(
                "Focus section",
                options=["auto", "alarms", "sensor_data", "recipe_steps", "events", "metadata"],
            )
            parsing_goal = st.text_area(
                "Parsing goal",
                height=80,
                placeholder="e.g. find the main fault and related sensor values",
            )
            vendor_label = st.text_input(
                "Vendor label (optional)",
                placeholder="e.g. ASML EUV Scanner, Vendor A Dry Etch",
            )

        if st.button("Process Log", type="primary"):
            if not uploaded and not pasted.strip():
                st.error("Please provide a file or paste log text.")
            else:
                with st.spinner("Parsing log..."):
                    try:
                        data = {
                            "raw_text": pasted.strip() or None,
                            "fields_of_interest": fields_of_interest.strip() or None,
                            "focus_section": None if focus_section == "auto" else focus_section,
                            "parsing_goal": parsing_goal.strip() or None,
                            "vendor_label": vendor_label.strip() or None,
                        }

                        if uploaded:
                            files = {
                                "file": (
                                    uploaded.name,
                                    uploaded.getvalue(),
                                    uploaded.type or "application/octet-stream",
                                )
                            }
                            resp = requests.post(
                                f"{API_BASE}/upload-log",
                                data=data,
                                files=files,
                                timeout=60,
                            )
                        else:
                            resp = requests.post(
                                f"{API_BASE}/upload-log",
                                data=data,
                                timeout=60,
                            )

                        st.session_state["last_response"] = resp.json()
                    except Exception as exc:
                        st.error(f"Failed to call API: {exc}")

    with col2:
        if "last_response" in st.session_state:
            result = st.session_state["last_response"]
            st.subheader("Result")

            # Summary banner
            summary = result.get("human_summary", "")
            if summary:
                st.info(f"**Engineer summary:** {summary}")

            # Status pills
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                fmt = result.get("format_detected", "-")
                st.metric("Format", fmt.upper())
            with col_b:
                conf = result.get("confidence", 0)
                st.metric("Confidence", f"{conf:.0%}")
            with col_c:
                status = result.get("source_status", "-")
                llm = "Yes" if result.get("llm_used") else "No (profile)"
                st.metric("LLM used", llm)

            if result.get("needs_review"):
                st.warning("⚠️ Low confidence — manual review recommended.")

            if result.get("vendor_profile"):
                st.success(f"✅ Matched vendor profile: {result['vendor_profile']}")

            # Normalized payload as clean table
            st.subheader("Normalized fields")
            normalized = result.get("normalized_payload", {})
            if normalized:
                rows = [{"Field": k, "Value": str(v)} for k, v in normalized.items()]
                st.dataframe(rows, use_container_width=True, hide_index=True)

            with st.expander("Raw payload (pre-normalization)"):
                st.json(result.get("raw_payload", {}))

            with st.expander("Full API response"):
                st.json(result)


# ─────────────────────────────────────────────
# Tab 2: Demo Mode — the presentation story
# ─────────────────────────────────────────────
with tab_demo:
    st.subheader("Demo: Same Event, Multiple Vendor Formats → One Canonical Schema")
    st.markdown(
        "This runs five synthetic logs — all describing the same vacuum fault on ETCH_TOOL_42 — "
        "through the pipeline. Watch them all normalize to the same fields."
    )

    if st.button("Run Demo", type="primary"):
        with st.spinner("Running all synthetic logs..."):
            try:
                resp = requests.get(f"{API_BASE}/demo", timeout=120)
                st.session_state["demo_results"] = resp.json()
            except Exception as exc:
                st.error(f"Demo failed: {exc}")

    if "demo_results" in st.session_state:
        demo = st.session_state["demo_results"]
        st.markdown(f"**Scenario:** {demo.get('demo_scenario', '')}")
        st.divider()

        results = demo.get("results", [])

        # Canonical fields we care about for the comparison table
        CANONICAL = [
            "event_type", "severity", "tool_id", "chamber_id",
            "temperature_c", "vacuum_pressure", "error_code", "timestamp",
        ]

        # Summary table
        rows = []
        for r in results:
            if "error" in r:
                continue
            row = {
                "Source": r["label"],
                "Format": r["format"].upper(),
                "Confidence": f"{r['confidence']:.0%}",
                "Status": r["source_status"],
            }
            payload = r.get("normalized_payload", {})
            for field in CANONICAL:
                row[field] = str(payload.get(field, "—"))
            rows.append(row)

        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)

        st.divider()

        # Per-source detail cards
        for r in results:
            with st.expander(f"📄 {r['label']} — {r.get('format', '?').upper()}"):
                summary = r.get("human_summary", "")
                if summary:
                    st.info(f"**Summary:** {summary}")
                st.json(r.get("normalized_payload", {}))


# ─────────────────────────────────────────────
# Tab 3: Recent logs
# ─────────────────────────────────────────────
with tab_logs:
    if st.button("Refresh"):
        try:
            resp = requests.get(f"{API_BASE}/logs", timeout=30)
            st.session_state["recent_logs"] = resp.json()
        except Exception as exc:
            st.error(f"Failed: {exc}")

    if "recent_logs" in st.session_state:
        items = st.session_state["recent_logs"].get("items", [])
        st.markdown(f"**{len(items)} logs**")

        table = []
        for item in items:
            payload = item.get("payload", {})
            table.append({
                "ID": item["id"],
                "Format": item["format_detected"],
                "Confidence": f"{item['confidence']:.0%}",
                "Event": payload.get("event_type", "—"),
                "Severity": payload.get("severity", "—"),
                "Tool": payload.get("tool_id", "—"),
                "Chamber": payload.get("chamber_id", "—"),
                "Review?": "⚠️" if item["needs_review"] else "✅",
                "Created": item["created_at"],
            })

        st.dataframe(table, use_container_width=True, hide_index=True)

        # Anomaly check
        if st.button("Run anomaly detection"):
            try:
                resp = requests.get(f"{API_BASE}/anomaly-check", timeout=30)
                anomaly = resp.json()
                if anomaly.get("available"):
                    anomalies = anomaly.get("anomalies", [])
                    if anomalies:
                        st.warning(f"⚠️ {len(anomalies)} anomalous log(s) detected")
                        st.dataframe(anomalies, use_container_width=True, hide_index=True)
                    else:
                        st.success("No anomalies detected.")
                else:
                    st.info(anomaly.get("message", "Anomaly check unavailable."))
            except Exception as exc:
                st.error(f"Failed: {exc}")


# ─────────────────────────────────────────────
# Tab 4: Vendor profiles
# ─────────────────────────────────────────────
with tab_profiles:
    st.subheader("Learned Vendor Profiles")
    st.markdown(
        "Every source that's been parsed with high confidence gets saved as a profile. "
        "When the same source appears again, Gemini is skipped — the pipeline uses the saved strategy."
    )

    if st.button("Load Profiles"):
        try:
            resp = requests.get(f"{API_BASE}/profiles", timeout=30)
            st.session_state["profiles"] = resp.json()
        except Exception as exc:
            st.error(f"Failed: {exc}")

    if "profiles" in st.session_state:
        profiles_data = st.session_state["profiles"].get("vendor_profiles", [])
        if profiles_data:
            st.dataframe(profiles_data, use_container_width=True, hide_index=True)
        else:
            st.info("No profiles yet. Process some logs to build up vendor profiles.")


# ─────────────────────────────────────────────
# Tab 5: Schema feedback
# ─────────────────────────────────────────────
with tab_feedback:
    st.subheader("Teach the Pipeline")
    st.markdown(
        "If a field was mapped incorrectly, you can provide a manual correction here. "
        "This rule is saved and applied to all future ingestions."
    )

    with st.form("feedback_form"):
        raw_key = st.text_input("Raw field name (e.g. TMP, VAC_PRESS, tmp_c)")
        canonical_key = st.text_input("Correct canonical name (e.g. temperature_c, vacuum_pressure)")
        submitted = st.form_submit_button("Save Rule")

        if submitted:
            if not raw_key.strip() or not canonical_key.strip():
                st.error("Provide both fields.")
            else:
                try:
                    resp = requests.post(
                        f"{API_BASE}/feedback",
                        json={"raw_key": raw_key.strip(), "canonical_key": canonical_key.strip()},
                        timeout=30,
                    )
                    if resp.ok:
                        st.success(resp.json().get("message", "Rule saved"))
                    else:
                        st.error(f"Error {resp.status_code}")
                except Exception as exc:
                    st.error(f"Failed: {exc}")

    st.divider()
    st.subheader("Current schema rules")
    if st.button("Load Rules"):
        try:
            resp = requests.get(f"{API_BASE}/schema-rules", timeout=30)
            data = resp.json()
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Manual rules**")
                st.json(data.get("manual_rules", {}))
            with col2:
                st.markdown("**Memory-promoted rules**")
                st.json(data.get("memory_promoted_rules", {}))
        except Exception as exc:
            st.error(f"Failed: {exc}")
