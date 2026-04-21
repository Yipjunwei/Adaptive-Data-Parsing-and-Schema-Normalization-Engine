"""Adaptive Tool Log Intelligence Pipeline — Streamlit UI v0.3 with dashboard/reporting."""
from __future__ import annotations

import time

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_BASE = "http://127.0.0.1:8000"
REFRESH_SECONDS = 10

st.set_page_config(
    page_title="Tool Log Intelligence",
    layout="wide",
    page_icon="⚙️",
)

st.title("⚙️ Adaptive Tool Log Intelligence Pipeline")

tab_upload, tab_dashboard, tab_logs, tab_profiles, tab_feedback = st.tabs(
    ["Upload Log", "Equipment Health Dashboard", "Recent Logs", "Vendor Profiles", "Schema Feedback"]
)

with tab_upload:
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Input")
        uploaded = st.file_uploader(
            "Upload log file (.txt, .log, .json, .xml, .csv, .bin)",
            type=["txt", "log", "json", "xml", "csv", "bin"],
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
                                timeout=90,
                            )
                        else:
                            resp = requests.post(
                                f"{API_BASE}/upload-log",
                                data=data,
                                timeout=90,
                            )

                        st.session_state["last_response"] = resp.json()
                    except Exception as exc:
                        st.error(f"Failed to call API: {exc}")

    with col2:
        if "last_response" in st.session_state:
            result = st.session_state["last_response"]
            st.subheader("Result")
            summary = result.get("human_summary", "")
            if summary:
                st.info(f"**Engineer summary:** {summary}")

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("Format", result.get("format_detected", "-").upper())
            with col_b:
                st.metric("Confidence", f"{result.get('confidence', 0):.0%}")
            with col_c:
                st.metric("LLM used", "Yes" if result.get("llm_used") else "No (profile)")

            if result.get("root_cause"):
                rc = result["root_cause"]
                st.success(f"**Likely cause:** {rc.get('most_likely_cause', '-')}")
                st.write(f"**Suggested action:** {rc.get('suggested_action', '-')}")

            st.subheader("Normalized fields")
            normalized = result.get("normalized_payload", {})
            if normalized:
                rows = [{"Field": k, "Value": str(v)} for k, v in normalized.items()]
                st.dataframe(rows, use_container_width=True, hide_index=True)

            with st.expander("Full API response"):
                st.json(result)

with tab_dashboard:
    left, right = st.columns([1, 3])

    with left:
        st.subheader("Dashboard controls")
        auto_refresh = st.checkbox("Auto-refresh every 10s", value=False)
        if st.button("Refresh tools"):
            try:
                st.session_state["tools_payload"] = requests.get(f"{API_BASE}/tools", timeout=30).json()
            except Exception as exc:
                st.error(f"Failed to load tools: {exc}")

        tools_payload = st.session_state.get("tools_payload")
        if tools_payload is None:
            try:
                tools_payload = requests.get(f"{API_BASE}/tools", timeout=30).json()
                st.session_state["tools_payload"] = tools_payload
            except Exception:
                tools_payload = {"items": []}

        tools = tools_payload.get("items", [])
        selected_tool = st.selectbox("Select tool", options=tools if tools else [""], index=0)
        limit = st.slider("Logs to analyze", min_value=20, max_value=500, value=200, step=20)

        if selected_tool and st.button("Generate PDF report", type="primary"):
            try:
                report_resp = requests.get(
                    f"{API_BASE}/reports/tool-health",
                    params={"tool_id": selected_tool, "limit": limit},
                    timeout=120,
                )
                if report_resp.ok:
                    st.download_button(
                        label="Download report",
                        data=report_resp.content,
                        file_name=f"tool_health_{selected_tool}.pdf",
                        mime="application/pdf",
                    )
                else:
                    st.error(f"Report generation failed: {report_resp.text}")
            except Exception as exc:
                st.error(f"Failed to generate report: {exc}")

    with right:
        if selected_tool:
            try:
                dashboard = requests.get(
                    f"{API_BASE}/dashboard/summary",
                    params={"tool_id": selected_tool, "limit": limit},
                    timeout=60,
                ).json()

                summary = dashboard.get("summary", {})
                latest_payload = dashboard.get("latest_payload", {})
                root_cause = dashboard.get("root_cause", {})
                timeline = dashboard.get("timeline", [])
                sev = summary.get("severity_breakdown", {})

                c1, c2 = st.columns([1, 1])
                with c1:
                    gauge = go.Figure(go.Indicator(
                        mode="gauge+number",
                        value=summary.get("health_score", 0),
                        title={"text": f"Health score - {selected_tool}"},
                        gauge={
                            "axis": {"range": [0, 100]},
                            "bar": {"color": "darkblue"},
                            "steps": [
                                {"range": [0, 50], "color": "#f8d7da"},
                                {"range": [50, 75], "color": "#fff3cd"},
                                {"range": [75, 100], "color": "#d1e7dd"},
                            ],
                        },
                    ))
                    gauge.update_layout(height=320, margin=dict(l=20, r=20, t=60, b=20))
                    st.plotly_chart(gauge, use_container_width=True)
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Avg confidence", f"{summary.get('avg_confidence', 0):.2f}")
                    m2.metric("Fault rate", f"{summary.get('fault_rate', 0):.2f}")
                    m3.metric("Dominant fault", summary.get("dominant_fault_type") or "-")

                with c2:
                    sev_df = pd.DataFrame([
                        {"severity": "critical", "count": sev.get("critical", 0)},
                        {"severity": "warning", "count": sev.get("warning", 0)},
                        {"severity": "info", "count": sev.get("info", 0)},
                    ])
                    donut = px.pie(sev_df, values="count", names="severity", hole=0.55, title="Severity breakdown")
                    donut.update_layout(height=320, margin=dict(l=20, r=20, t=60, b=20))
                    st.plotly_chart(donut, use_container_width=True)

                st.subheader("Fault type trend over time")
                if timeline:
                    timeline_df = pd.DataFrame(timeline)
                    bar = px.bar(
                        timeline_df,
                        x="period",
                        y="count",
                        color="event_type",
                        barmode="group",
                        title="Recurring fault type distribution",
                    )
                    bar.update_layout(xaxis_title="Time bucket", yaxis_title="Event count", height=360)
                    st.plotly_chart(bar, use_container_width=True)
                else:
                    st.info("No timeline data yet for this tool.")

                st.subheader("Root Cause Suggestion Panel")
                panel_left, panel_right = st.columns([1, 1])
                with panel_left:
                    st.markdown("**Latest normalized payload**")
                    st.json(latest_payload)
                with panel_right:
                    st.markdown("**Most likely cause**")
                    st.write(root_cause.get("most_likely_cause", "-"))
                    st.markdown("**Suggested action**")
                    st.write(root_cause.get("suggested_action", "-"))

            except Exception as exc:
                st.error(f"Failed to load dashboard: {exc}")

        if auto_refresh and selected_tool:
            time.sleep(REFRESH_SECONDS)
            st.rerun()

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

with tab_profiles:
    st.subheader("Learned Vendor Profiles")
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

with tab_feedback:
    st.subheader("Teach the Pipeline")
    with st.form("feedback_form"):
        raw_key = st.text_input("Raw field name (e.g. TMP, VAC_PRESS, tmp_c)")
        canonical_key = st.text_input("Correct canonical name (e.g. temperature_c, pressure_pa)")
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
