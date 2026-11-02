"""Streamlit entry point for the platform application control center."""

import streamlit as st

from application.dashboard_api import api_base_url, get_liveness, get_readiness, grafana_settings
from application.dashboard_ui import apply_dashboard_styles, status_message
from application.dashboard_pages import (
    anomalies,
    audit,
    grafana,
    infrastructure,
    jobs,
    overview,
    remediation,
)


PAGES = (
    "Overview",
    "Infrastructure Monitoring",
    "Anomaly Detection",
    "Job Management",
    "Remediation Center",
    "Audit History",
    "Grafana Integration",
)


st.set_page_config(
    page_title="Data Processing Platform",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_dashboard_styles()

with st.sidebar:
    st.markdown('<div class="nav-brand">Data Processing Platform</div>', unsafe_allow_html=True)
    st.markdown('<div class="nav-caption">Application control center</div>', unsafe_allow_html=True)
    st.divider()
    selected_page = st.radio(
        "Workspace navigation",
        PAGES,
        index=0,
        label_visibility="collapsed",
        key="dashboard_navigation",
    )
    st.divider()
    st.caption("Backend connection")
    live_status, _, live_error = get_liveness()
    status_message("Connected" if live_status == 200 else "Unavailable", live_status == 200, None if live_status == 200 else live_error)
    ready_status, ready_data, ready_error = get_readiness()
    ready = ready_status == 200 and bool((ready_data or {}).get("ready"))
    if ready_status == 503:
        failed = [
            name.replace("_", " ")
            for name, okay in (ready_data or {}).get("components", {}).items()
            if not okay
        ]
        ready_error = ", ".join(failed) or "readiness unavailable"
    status_message("Ready" if ready else "Not ready", ready, ready_error if not ready else None)
    st.caption(f"FastAPI · {api_base_url()}")
    st.caption("Grafana · configured" if grafana_settings()[0] else "Grafana · optional / not configured")


PAGE_RENDERERS = {
    "Overview": overview.render,
    "Infrastructure Monitoring": infrastructure.render,
    "Anomaly Detection": anomalies.render,
    "Job Management": jobs.render,
    "Remediation Center": remediation.render,
    "Audit History": audit.render,
    "Grafana Integration": grafana.render,
}

PAGE_RENDERERS[selected_page]()
