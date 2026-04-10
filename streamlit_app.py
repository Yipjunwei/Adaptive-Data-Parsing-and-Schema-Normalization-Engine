from __future__ import annotations

import requests
import streamlit as st

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="Adaptive Log Intelligence", layout="wide")
st.title("Adaptive Tool Log Intelligence Pipeline")

st.markdown("Upload a log file or paste raw tool logs to parse and normalize.")

col1, col2 = st.columns(2)

with col1:
    uploaded = st.file_uploader("Upload log file", type=["txt", "log", "json", "xml", "csv"])
    pasted = st.text_area("Or paste raw log text", height=180)
    if st.button("Process Log"):
        try:
            if uploaded:
                files = {"file": (uploaded.name, uploaded.getvalue())}
                resp = requests.post(f"{API_BASE}/upload-log", files=files, timeout=30)
            else:
                resp = requests.post(f"{API_BASE}/upload-log", data={"raw_text": pasted}, timeout=30)
            st.session_state["last_response"] = resp.json()
        except Exception as exc:
            st.error(f"Failed to call API: {exc}")

with col2:
    if "last_response" in st.session_state:
        st.subheader("Result")
        st.json(st.session_state["last_response"])

st.divider()

st.subheader("Feedback Rule")
with st.form("feedback_form"):
    raw_key = st.text_input("Raw key (example: TMP)")
    canonical_key = st.text_input("Canonical key (example: temperature_c)")
    submitted = st.form_submit_button("Save Rule")
    if submitted and raw_key and canonical_key:
        resp = requests.post(
            f"{API_BASE}/feedback",
            json={"raw_key": raw_key, "canonical_key": canonical_key},
            timeout=30,
        )
        st.success(resp.json().get("message", "Rule saved"))

st.divider()

if st.button("Refresh Recent Logs"):
    try:
        logs = requests.get(f"{API_BASE}/logs", timeout=30).json()
        st.session_state["recent_logs"] = logs
    except Exception as exc:
        st.error(f"Failed to fetch logs: {exc}")

if "recent_logs" in st.session_state:
    st.subheader("Recent Logs")
    st.json(st.session_state["recent_logs"])
