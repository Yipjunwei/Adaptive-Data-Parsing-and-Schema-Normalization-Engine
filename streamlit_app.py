from __future__ import annotations

import requests
import streamlit as st

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="Adaptive Log Intelligence", layout="wide")
st.title("Adaptive Tool Log Intelligence Pipeline")
st.markdown("Upload a log file or paste raw tool logs to parse and normalize.")

col1, col2 = st.columns(2)

with col1:
    uploaded = st.file_uploader(
        "Upload log file",
        type=["txt", "log", "json", "xml", "csv"],
    )

    pasted = st.text_area(
        "Or paste raw log text",
        height=180,
        placeholder="Paste raw tool log here...",
    )

    st.markdown("### Optional Parsing Guidance")

    fields_of_interest = st.text_input(
        "Fields of interest",
        placeholder="e.g. temperature_c, pressure_pa, chamber_id, event_type",
    )

    focus_section = st.selectbox(
        "Focus section",
        options=["auto", "alarms", "sensor_data", "recipe_steps", "events", "metadata"],
        index=0,
    )

    parsing_goal = st.text_area(
        "Parsing goal",
        height=100,
        placeholder="e.g. find the main fault and related sensor values",
    )

    if st.button("Process Log"):
        try:
            data = {
                "raw_text": pasted.strip() or None,
                "fields_of_interest": fields_of_interest.strip() or None,
                "focus_section": None if focus_section == "auto" else focus_section,
                "parsing_goal": parsing_goal.strip() or None,
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

        st.subheader("Full Response")
        st.json(result)

st.divider()

st.subheader("Feedback Rule")
with st.form("feedback_form"):
    raw_key = st.text_input("Raw key (example: TMP)")
    canonical_key = st.text_input("Canonical key (example: temperature_c)")
    submitted = st.form_submit_button("Save Rule")

    if submitted:
        if not raw_key.strip() or not canonical_key.strip():
            st.error("Please provide both raw key and canonical key.")
        else:
            try:
                resp = requests.post(
                    f"{API_BASE}/feedback",
                    json={
                        "raw_key": raw_key.strip(),
                        "canonical_key": canonical_key.strip(),
                    },
                    timeout=30,
                )

                if resp.ok:
                    st.success(resp.json().get("message", "Rule saved"))
                else:
                    st.error(f"Failed to save rule: {resp.status_code}")
                    try:
                        st.json(resp.json())
                    except Exception:
                        st.text(resp.text)

            except Exception as exc:
                st.error(f"Failed to save rule: {exc}")

st.divider()

if st.button("Refresh Recent Logs"):
    try:
        logs_resp = requests.get(f"{API_BASE}/logs", timeout=30)
        if logs_resp.ok:
            st.session_state["recent_logs"] = logs_resp.json()
        else:
            st.error(f"Failed to fetch logs: {logs_resp.status_code}")
    except Exception as exc:
        st.error(f"Failed to fetch logs: {exc}")

if "recent_logs" in st.session_state:
    st.subheader("Recent Logs")
    st.json(st.session_state["recent_logs"])