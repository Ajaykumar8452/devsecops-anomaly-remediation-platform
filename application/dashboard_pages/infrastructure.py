import pandas as pd
import streamlit as st

from application.dashboard_api import (
    get_http_metrics,
    get_metrics_history,
    get_system_metrics,
)
from application.dashboard_ui import page_header, timestamp_ist


@st.fragment(run_every="3s")
def _live_infrastructure():
    metrics = get_system_metrics()
    history = get_metrics_history()
    http = get_http_metrics()

    st.subheader("Current resource snapshot")
    columns = st.columns(4)
    if metrics:
        columns[0].metric("Backend process CPU", f"{metrics.get('process_cpu_percent', 0):.1f}%")
        columns[1].metric("Backend process RSS", f"{metrics.get('process_memory_mb', 0):.1f} MB")
        columns[2].metric("Host system CPU", f"{metrics.get('system_cpu_percent', 0):.1f}%")
        columns[3].metric("Host system memory", f"{metrics.get('system_memory_percent', 0):.1f}%")
    else:
        st.warning("Current resource metrics are unavailable from `/metrics/system`.")

    st.caption("Backend values are for the FastAPI process. Host values are system-wide, not Kubernetes Pod or Deployment metrics.")
    if history is None:
        st.warning("Recent sample history is unavailable from `/metrics/history`.")
    else:
        samples = history.get("samples", [])
        if samples:
            frame = pd.DataFrame(samples)
            frame["timestamp"] = pd.to_datetime(frame.get("timestamp"), errors="coerce", utc=True)
            frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp").tail(60).set_index("timestamp")
            st.markdown("**Recent sample context**")
            st.caption("Compact recent samples only. Use Grafana for extended infrastructure trends.")
            cpu_keys = [key for key in ("process_cpu_percent", "system_cpu_percent") if key in frame]
            memory_keys = [key for key in ("process_memory_mb", "system_memory_percent") if key in frame]
            cpu_col, memory_col = st.columns(2)
            with cpu_col:
                if cpu_keys:
                    st.line_chart(frame[cpu_keys], height=220)
                    st.caption("CPU values are percentages; backend process and host are separate series.")
            with memory_col:
                if memory_keys:
                    st.line_chart(frame[memory_keys], height=220)
                    st.caption("Process RSS is MB; host memory is percent. These use different units.")
        else:
            st.info("No historical samples have been collected yet.")

    st.divider()
    st.subheader("HTTP service snapshot")
    if not http:
        st.warning("HTTP request metrics are unavailable from `/metrics/http`.")
        return
    status_codes = http.get("status_codes", {})
    server_errors = sum(int(value) for code, value in status_codes.items() if str(code).startswith("5"))
    client_errors = sum(int(value) for code, value in status_codes.items() if str(code).startswith("4"))
    request_cols = st.columns(4)
    request_cols[0].metric("Total requests", http.get("total_requests", "Unavailable"))
    request_cols[1].metric("Average latency", f"{http.get('average_latency_ms', 0):.2f} ms")
    request_cols[2].metric("HTTP 5xx responses", server_errors)
    request_cols[3].metric("In-flight requests", http.get("in_flight_requests", "Unavailable"))
    st.caption(f"HTTP 4xx responses: {client_errors}")

    recent = http.get("recent_requests", [])
    if not recent:
        st.info("No HTTP requests have been recorded yet.")
        return
    frame = pd.DataFrame(recent)
    if "timestamp" in frame:
        frame["timestamp"] = frame["timestamp"].map(timestamp_ist)
    columns = [key for key in ("timestamp", "method", "endpoint", "status_code", "latency_ms") if key in frame]
    if columns:
        st.dataframe(frame[columns].tail(25), width="stretch", hide_index=True)


def render():
    page_header(
        "Infrastructure Monitoring",
        "Infrastructure monitoring",
        "Current application and host signals, with compact recent context. Grafana is the home for long-range infrastructure dashboards.",
    )
    _live_infrastructure()
