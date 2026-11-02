import streamlit as st

from application.dashboard_api import (
    get_active_alerts,
    get_anomaly_history,
    get_anomaly_state,
)
from application.dashboard_ui import page_header, render_alert_table, timestamp_ist


SIGNAL_GROUPS = (
    ("CPU", (("backend_cpu_percent", "%"),)),
    ("Memory", (("backend_process_memory_mb", "MB"), ("system_memory_percent", "%"))),
    ("Application health", (("application_health", ""),)),
    ("HTTP quality", (("http_5xx_error_rate_percent", "%"), ("average_latency_ms", "ms"))),
)


def _render_signal(signal_key, unit, signal):
    label = signal.get("label", signal_key.replace("_", " ").title())
    state = signal.get("state", "UNKNOWN")
    metric_status = signal.get("metric_status", "unknown")
    value = signal.get("current_value")
    policy = signal.get("policy", {})
    unknown = metric_status != "ok" or value is None

    with st.container(border=True):
        st.markdown(f"#### {label}")
        if unknown:
            st.info(f"Metric state: UNKNOWN · last evaluator state: {state}")
            if signal.get("unknown_reason"):
                st.caption(f"Metric unavailable: {signal['unknown_reason']}")
            shown_value = "Unknown"
        elif state == "CONFIRMED":
            st.error(f"Detection state: {state}")
            shown_value = "Healthy" if signal_key == "application_health" and value else (
                "Unhealthy" if signal_key == "application_health" else f"{float(value):.2f} {unit}".strip()
            )
        elif state in {"PENDING", "RECOVERING"}:
            st.warning(f"Detection state: {state}")
            shown_value = "Healthy" if signal_key == "application_health" and value else (
                "Unhealthy" if signal_key == "application_health" else f"{float(value):.2f} {unit}".strip()
            )
        else:
            st.success(f"Detection state: {state}")
            shown_value = "Healthy" if signal_key == "application_health" and value else (
                "Unhealthy" if signal_key == "application_health" else f"{float(value):.2f} {unit}".strip()
            )

        trigger = policy.get("trigger_threshold")
        recovery = policy.get("recovery_threshold")
        if signal_key == "application_health":
            trigger = "Unhealthy"
            recovery = "Healthy"
        elif trigger is not None:
            trigger = f"{trigger} {unit}".strip()
        else:
            trigger = "Not configured"
        if signal_key != "application_health":
            recovery = f"{recovery} {unit}".strip() if recovery is not None else "Not configured"

        columns = st.columns(4)
        columns[0].metric("Current value", shown_value)
        columns[1].metric("Trigger", trigger)
        columns[2].metric("Recovery", recovery)
        columns[3].metric("Policy mode", signal.get("policy_mode", "unknown").replace("_", " ").title())
        persistence = float(policy.get("persistence_seconds") or 0)
        recovery_seconds = float(policy.get("recovery_seconds") or 0)
        pending_elapsed = float(signal.get("persistence_elapsed_seconds") or 0)
        recovery_elapsed = float(signal.get("recovery_elapsed_seconds") or 0)
        st.caption(
            f"Confirmation: {pending_elapsed:.1f}/{persistence:g} sec · "
            f"Recovery: {recovery_elapsed:.1f}/{recovery_seconds:g} sec · "
            f"Cooldown: {float(policy.get('cooldown_seconds') or 0):g} sec"
        )
        st.caption(f"Metric timestamp: {timestamp_ist(signal.get('metric_timestamp'))}")
        if signal_key == "application_health":
            checks = signal.get("components", {})
            if checks:
                st.caption("Internal checks: " + ", ".join(
                    f"{name.replace('_', ' ')}={'OK' if value else 'FAILED'}"
                    for name, value in checks.items()
                ))
        if signal.get("active_alert_id"):
            st.caption(f"Active alert: {signal['active_alert_id']}")
        if signal.get("pending_since"):
            st.caption(f"Pending since: {timestamp_ist(signal['pending_since'])}")
        if signal.get("recovery_since"):
            st.caption(f"Recovery since: {timestamp_ist(signal['recovery_since'])}")


@st.fragment(run_every="3s")
def _live_anomaly_content():
    anomaly = get_anomaly_state()
    if anomaly is None:
        st.warning("Anomaly data is unavailable. Check `/anomalies/state` and backend connectivity.")
        return

    signals = anomaly.get("signals", {})
    for group, entries in SIGNAL_GROUPS:
        st.subheader(group)
        columns = st.columns(len(entries))
        for index, (signal_key, unit) in enumerate(entries):
            signal = signals.get(signal_key)
            with columns[index]:
                if signal is None:
                    _render_signal(signal_key, unit, {"state": "UNKNOWN", "metric_status": "unknown", "unknown_reason": "signal not returned by API"})
                else:
                    _render_signal(signal_key, unit, signal)

    active = get_active_alerts()
    if active is None:
        active = [
            signal["active_alert"]
            for signal in signals.values()
            if signal.get("active_alert")
        ]
        st.warning("The active-alert endpoint is unavailable; showing active records included in the state response.")
    render_alert_table(active, title="Active alerts", empty_message="No active alerts.")

    history = get_anomaly_history(limit=500)
    if history is None:
        history = anomaly.get("alert_history", [])
    render_alert_table(history, title="Alert history", empty_message="No confirmed alert history is available.")
    st.caption(f"Last evaluator check: {timestamp_ist(anomaly.get('checked_at'))}")


def render():
    page_header(
        "Detection & Alert Management",
        "Anomaly detection",
        "Live state, policy context and persisted alert lifecycle for all six monitored signals.",
    )
    _live_anomaly_content()
