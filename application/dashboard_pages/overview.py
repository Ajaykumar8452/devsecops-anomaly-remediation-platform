import os

import streamlit as st

from application.dashboard_api import (
    get_active_alerts,
    get_anomaly_history,
    get_anomaly_state,
    get_http_metrics,
    get_liveness,
    get_readiness,
    get_system_metrics,
)
from application.dashboard_ui import page_header, render_alert_table, status_message


def _metric(column, label, value, help_text=None):
    column.metric(label, value, help=help_text)


def render():
    page_header(
        "Application Control Center",
        "Overview",
        "A current operational summary for the analytics platform.",
    )

    live_status, live_payload, live_error = get_liveness()
    ready_status, ready_payload, ready_error = get_readiness()
    live_ok = live_status == 200
    ready_ok = ready_status == 200 and bool((ready_payload or {}).get("ready"))

    status_cols = st.columns(3)
    with status_cols[0]:
        with st.container(border=True):
            st.markdown("**Backend connectivity**")
            status_message(
                "Connected" if live_ok else "Unavailable",
                live_ok,
                "FastAPI liveness" if live_ok else live_error,
            )
    with status_cols[1]:
        with st.container(border=True):
            st.markdown("**Application readiness**")
            if ready_status == 503:
                missing = [
                    name.replace("_", " ")
                    for name, available in (ready_payload or {}).get("components", {}).items()
                    if not available
                ]
                detail = ", ".join(missing) or "readiness check failed"
            else:
                detail = ready_error
            status_message(
                "Ready" if ready_ok else "Not ready",
                ready_ok,
                detail,
            )
    with status_cols[2]:
        with st.container(border=True):
            st.markdown("**Grafana observability**")
            grafana_configured = bool(os.getenv("GRAFANA_BASE_URL", "").strip())
            status_message(
                "Configured" if grafana_configured else "Optional · not configured",
                True if grafana_configured else None,
                None,
            )

    metrics = get_system_metrics() if live_ok else None
    http = get_http_metrics() if live_ok else None
    anomaly = get_anomaly_state() if live_ok else None
    active_alerts = get_active_alerts() if live_ok else None
    history = get_anomaly_history(limit=10) if live_ok else None

    st.subheader("Current operating snapshot")
    metric_cols = st.columns(4)
    if metrics:
        _metric(metric_cols[0], "Backend process CPU", f"{metrics.get('process_cpu_percent', 0):.1f}%")
        _metric(metric_cols[1], "Backend process RSS", f"{metrics.get('process_memory_mb', 0):.1f} MB")
        _metric(metric_cols[2], "Host system CPU", f"{metrics.get('system_cpu_percent', 0):.1f}%")
        _metric(metric_cols[3], "Host system memory", f"{metrics.get('system_memory_percent', 0):.1f}%")
    else:
        for col, label in zip(metric_cols, ("Backend CPU", "Backend RSS", "Host CPU", "Host memory")):
            _metric(col, label, "Unavailable")
        st.warning("Resource metrics are unavailable. Verify the backend and `/metrics/system`.")

    http_cols = st.columns(4)
    if http:
        _metric(http_cols[0], "HTTP requests", http.get("total_requests", "Unavailable"))
        _metric(http_cols[1], "Average response latency", f"{http.get('average_latency_ms', 0):.2f} ms")
        codes = http.get("status_codes", {})
        errors_5xx = sum(int(count) for code, count in codes.items() if str(code).startswith("5"))
        _metric(http_cols[2], "HTTP 5xx responses", errors_5xx)
        _metric(http_cols[3], "Requests in progress", http.get("in_flight_requests", "Unavailable"))
    else:
        for col, label in zip(http_cols, ("HTTP requests", "Average latency", "HTTP 5xx", "In flight")):
            _metric(col, label, "Unavailable")

    left, right = st.columns([1, 2])
    with left:
        st.subheader("Anomaly status")
        if active_alerts is None:
            st.metric("Active anomalies", "Unavailable")
            st.warning("Active alert data is unavailable.")
        else:
            st.metric("Active anomalies", len(active_alerts))
        if anomaly:
            states = anomaly.get("signals", {})
            unknown = sum(signal.get("metric_status") != "ok" for signal in states.values())
            st.caption(f"{len(states)} signals · {unknown} with UNKNOWN or unavailable metrics")
        elif anomaly is None:
            st.caption("Signal state is unavailable.")
    with right:
        render_alert_table(
            history,
            title="Recent alerts",
            limit=5,
            empty_message="No alert records are available.",
        )

    st.caption("Host system metrics describe this machine. Backend process metrics describe FastAPI only.")
