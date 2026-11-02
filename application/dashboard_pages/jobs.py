import pandas as pd
import streamlit as st

from application.dashboard_api import get_jobs, submit_job
from application.dashboard_ui import page_header, timestamp_ist


WORKLOAD_LABELS = {
    "normal": "Normal workload",
    "cpu_intensive": "CPU intensive",
    "memory_intensive": "Memory intensive",
    "mixed": "Mixed CPU and memory workload",
}


def render():
    page_header(
        "Job Operations",
        "Job management",
        "Submit an explicit processing workload and review results returned by the backend.",
    )

    st.subheader("Submit a processing job")
    with st.form("job_submission_form"):
        workload = st.selectbox(
            "Workload type",
            list(WORKLOAD_LABELS),
            format_func=lambda key: WORKLOAD_LABELS[key],
        )
        iterations = st.slider("Iterations", min_value=1, max_value=20, value=1)
        submitted = st.form_submit_button("Run processing job", type="primary")

    if submitted:
        with st.spinner("Processing job…"):
            result, error = submit_job(workload, iterations)
        if error:
            st.error(f"Job submission failed: {error}")
        elif result is not None:
            status = str(result.get("status", "returned by backend")).lower()
            if status == "completed":
                st.success("Job completed.")
            elif status == "failed":
                st.error("Backend reported that the job failed.")
            else:
                st.info(f"Backend returned job status: {status}")
            st.json(result)

    st.divider()
    st.subheader("Execution history")
    jobs = get_jobs()
    if jobs is None:
        st.warning("Job history is unavailable from `/jobs`.")
        return
    if not jobs:
        st.info("No jobs are recorded by the backend yet.")
        return

    frame = pd.DataFrame(jobs)
    if "completed_at" in frame:
        frame["completed_at"] = frame["completed_at"].map(timestamp_ist)
    total = len(frame)
    statuses = frame.get("status", pd.Series(dtype=str)).astype(str).str.lower()
    completed = int((statuses == "completed").sum())
    failed = int((statuses == "failed").sum())
    durations = pd.to_numeric(frame.get("duration_seconds"), errors="coerce")
    average = float(durations.mean()) if durations is not None and durations.notna().any() else None
    cards = st.columns(4)
    cards[0].metric("Recorded jobs", total)
    cards[1].metric("Completed", completed)
    cards[2].metric("Failed", failed)
    cards[3].metric("Average duration", f"{average:.3f} s" if average is not None else "Unavailable")

    display_columns = [
        "job_id", "workload", "iterations", "status", "duration_seconds",
        "peak_process_memory_mb", "completed_at",
    ]
    visible = [column for column in display_columns if column in frame]
    st.dataframe(frame[visible], width="stretch", hide_index=True)

    if "duration_seconds" in frame:
        duration_frame = frame[["duration_seconds"]].copy()
        duration_frame["duration_seconds"] = pd.to_numeric(duration_frame["duration_seconds"], errors="coerce")
        duration_frame = duration_frame.dropna()
        if not duration_frame.empty:
            duration_frame.index = [f"Job {index + 1}" for index in range(len(duration_frame))]
            st.markdown("**Execution duration**")
            st.bar_chart(duration_frame, height=230)

    if "peak_process_memory_mb" in frame:
        peak_frame = frame[[column for column in ("workload", "peak_process_memory_mb") if column in frame]].copy()
        peak_frame["peak_process_memory_mb"] = pd.to_numeric(peak_frame["peak_process_memory_mb"], errors="coerce")
        peak_frame = peak_frame.dropna(subset=["peak_process_memory_mb"])
        if not peak_frame.empty:
            st.markdown("**Peak backend process memory by job**")
            st.bar_chart(peak_frame.set_index("workload")["peak_process_memory_mb"], height=230)
    st.caption("The current backend records jobs in memory; history reflects only records returned by `/jobs`.")
