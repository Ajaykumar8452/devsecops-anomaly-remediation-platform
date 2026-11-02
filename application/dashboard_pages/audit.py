import streamlit as st

from application.dashboard_api import get_anomaly_events, get_anomaly_history
from application.dashboard_ui import page_header, prepare_event_dataframe, render_alert_table


def render():
    page_header(
        "Operational Record",
        "Audit history",
        "Persisted anomaly lifecycle events and alert history from the existing backend APIs.",
    )
    events = get_anomaly_events(limit=1000)
    if events is None:
        st.warning("Lifecycle events are unavailable from `/anomalies/events`.")
    elif not events:
        st.info("No lifecycle events have been recorded.")
    else:
        frame = prepare_event_dataframe(events)
        columns = [
            key for key in (
                "event_id", "occurred_at", "event_type", "signal", "target_id",
                "alert_id", "observed_value", "details",
            ) if key in frame
        ]
        st.dataframe(frame[columns], width="stretch", hide_index=True)

    history = get_anomaly_history(limit=500)
    render_alert_table(history, title="Alert lifecycle records", empty_message="No alerts have been recorded.")
    st.divider()
    st.subheader("Remediation audit")
    st.info("Pending implementation. No remediation executions or audit records are available.")
