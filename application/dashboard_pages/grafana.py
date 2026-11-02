import streamlit as st

from application.dashboard_api import (
    check_grafana,
    grafana_internal_url,
    grafana_settings,
    valid_http_url,
)
from application.dashboard_ui import page_header


def render():
    page_header(
        "External Observability",
        "Grafana integration",
        "Infrastructure time series and monitoring dashboards are owned by Grafana when it is configured.",
    )
    base_url, dashboard_url = grafana_settings()
    if not base_url:
        st.info("Grafana is optional and is not configured. The application dashboard remains fully usable without it.")
        st.markdown("Configure `GRAFANA_BASE_URL` to add your Grafana instance.")
        return

    if not valid_http_url(base_url):
        st.error("`GRAFANA_BASE_URL` must be a valid HTTP or HTTPS URL.")
        return

    target = dashboard_url or base_url
    if dashboard_url and not valid_http_url(dashboard_url):
        st.warning("`GRAFANA_DASHBOARD_URL` is invalid; the configured base URL will be used instead.")
        target = base_url

    available, error = check_grafana(
        base_url,
        health_url=grafana_internal_url() or base_url,
    )
    if available:
        st.success("Grafana is reachable.")
        st.link_button("Open Grafana dashboard", target, type="primary")
        st.caption(f"Configured base URL: {base_url}")
        dashboards = (
            ("Application Overview", "application-overview"),
            ("HTTP Performance", "http-performance"),
            ("Anomaly Monitoring", "anomaly-monitoring"),
            ("Job Analytics", "job-analytics"),
        )
        st.subheader("Provisioned dashboards")
        columns = st.columns(2)
        for index, (title, uid) in enumerate(dashboards):
            columns[index % 2].link_button(
                title,
                f"{base_url}/d/{uid}/{uid}",
                use_container_width=True,
            )
    else:
        st.warning("Grafana is configured but currently unavailable. Streamlit monitoring remains available.")
        st.caption(error or "Grafana health check failed.")
        st.link_button("Try opening Grafana", target)
