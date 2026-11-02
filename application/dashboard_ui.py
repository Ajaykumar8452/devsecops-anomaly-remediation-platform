"""Shared styling, status and timestamp helpers for dashboard pages."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st


def apply_dashboard_styles():
    st.markdown(
        """
        <style>
        .block-container { max-width: 1500px; padding-top: 1.6rem; padding-bottom: 3rem; }
        [data-testid="stSidebar"] { border-right: 1px solid #243247; }
        [data-testid="stMetric"] {
            background: #111b2c; border: 1px solid #27364c; border-radius: 12px;
            padding: 0.9rem 1rem; min-height: 108px;
        }
        [data-testid="stMetricLabel"] { color: #9aabc1; font-size: 0.82rem; }
        [data-testid="stMetricValue"] { color: #edf4ff; font-weight: 650; }
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-color: #27364c !important; border-radius: 12px;
            background: rgba(17, 27, 44, 0.42);
        }
        h1, h2, h3 { letter-spacing: -0.025em; }
        .eyebrow { color: #69b7d5; text-transform: uppercase; letter-spacing: 0.12em;
            font-size: 0.72rem; font-weight: 700; margin-bottom: 0.25rem; }
        .page-description { color: #9aabc1; margin-top: -0.35rem; margin-bottom: 1.25rem; }
        .nav-brand { color: #edf4ff; font-size: 1.05rem; font-weight: 700; }
        .nav-caption { color: #8fa0b6; font-size: 0.78rem; }
        hr { border-color: #263449; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(eyebrow: str, title: str, description: str):
    st.markdown(f'<div class="eyebrow">{html.escape(eyebrow)}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(
        f'<div class="page-description">{html.escape(description)}</div>',
        unsafe_allow_html=True,
    )


def timestamp_ist(value):
    if not value:
        return "—"
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return "—"
    return parsed.tz_convert("Asia/Kolkata").strftime("%d-%b-%Y %I:%M:%S %p IST")


def prepare_alert_dataframe(alerts):
    frame = pd.DataFrame(alerts or [])
    if frame.empty:
        return frame

    for column in ("started_at", "confirmed_at", "resolved_at"):
        if column in frame.columns:
            frame[column] = frame[column].map(timestamp_ist)
    if "alert_id" in frame.columns:
        frame["short_alert_id"] = frame["alert_id"].astype(str).str[:8] + "…"
    if "status" in frame.columns:
        frame["display_status"] = frame["status"].map(
            {"confirmed": "CONFIRMED", "resolved": "RESOLVED"}
        ).fillna(frame["status"].astype(str).str.upper())
    if "observed_value" in frame.columns:
        frame["observed_value"] = pd.to_numeric(
            frame["observed_value"], errors="coerce"
        ).round(2)
    return frame


def render_alert_table(alerts, *, title=None, limit=None, empty_message="No alerts recorded."):
    if title:
        st.subheader(title)
    if alerts is None:
        st.warning("Alert data is unavailable from the backend.")
        return
    if not alerts:
        st.info(empty_message)
        return

    frame = prepare_alert_dataframe(alerts)
    if limit:
        frame = frame.head(limit)
    columns = [
        "short_alert_id", "signal", "display_status", "observed_value", "threshold",
        "started_at", "confirmed_at", "resolved_at",
    ]
    columns = [column for column in columns if column in frame.columns]
    st.dataframe(frame[columns], width="stretch", hide_index=True)
    with st.expander("View complete alert IDs and details"):
        st.dataframe(
            frame.drop(columns=["short_alert_id", "display_status"], errors="ignore"),
            width="stretch",
            hide_index=True,
        )


def prepare_event_dataframe(events):
    frame = pd.DataFrame(events or [])
    if frame.empty:
        return frame
    if "occurred_at" in frame.columns:
        frame["occurred_at"] = frame["occurred_at"].map(timestamp_ist)
    if "details_json" in frame.columns:
        frame["details"] = frame["details_json"]
    return frame


def status_message(label: str, healthy: bool | None, detail: str | None = None):
    text = label if not detail else f"{label} · {detail}"
    if healthy is True:
        st.success(text)
    elif healthy is False:
        st.error(text)
    else:
        st.info(text)
