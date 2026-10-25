
import requests
import pandas as pd
import streamlit as st

API_URL = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="Data Processing Platform",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Data Processing & Job Analytics")
st.caption(
    "Submit processing jobs, inspect results, and monitor system resources."
)

# --------------------------------------------------
# 1. Backend connection
# --------------------------------------------------

def get_metrics_history():
    try:
        response = requests.get(
            f"{API_URL}/metrics/history",
            timeout=5,
        )
        response.raise_for_status()
        return response.json().get("samples", [])
    except requests.RequestException:
        return []

def get_system_metrics():
    try:
        response = requests.get(
            f"{API_URL}/metrics/system",
            timeout=5,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


try:
    health_response = requests.get(
        f"{API_URL}/health",
        timeout=3,
    )
    api_online = health_response.status_code == 200
except requests.RequestException:
    api_online = False

if api_online:
    st.success("Backend API: Connected")
else:
    st.error(
        "Backend API unavailable. Start FastAPI on port 8000."
    )

# --------------------------------------------------
# 2. Retrieve job history
# --------------------------------------------------

jobs = []

if api_online:
    try:
        response = requests.get(
            f"{API_URL}/jobs",
            timeout=5,
        )
        response.raise_for_status()
        jobs = response.json().get("jobs", [])
    except requests.RequestException as exc:
        st.error(f"Could not retrieve jobs: {exc}")

df = pd.DataFrame(jobs)

# --------------------------------------------------
# 3. Job statistics
# --------------------------------------------------

total = len(df)

completed = (
    int((df["status"] == "completed").sum())
    if total else 0
)

failed = (
    int((df["status"] == "failed").sum())
    if total else 0
)

avg_duration = (
    float(df["duration_seconds"].mean())
    if total else 0.0
)

st.subheader("📋 Job Overview")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Jobs", total)
col2.metric("Completed", completed)
col3.metric("Failed", failed)
col4.metric("Avg Duration", f"{avg_duration:.3f} s")

# --------------------------------------------------
# 4. CPU and memory monitoring
# --------------------------------------------------

st.divider()
st.subheader("💻 Resource Utilization")

metrics = get_system_metrics() if api_online else None

if metrics:
    cpu_col, mem_col, sys_cpu_col, sys_mem_col = st.columns(4)

    cpu_col.metric(
        "Backend CPU",
        f"{metrics['process_cpu_percent']:.1f}%",
        help="CPU utilization reported for the FastAPI process.",
    )

    mem_col.metric(
        "Backend Memory",
        f"{metrics['process_memory_mb']:.1f} MB",
        help="Resident memory used by the FastAPI process.",
    )

    sys_cpu_col.metric(
        "System CPU",
        f"{metrics['system_cpu_percent']:.1f}%",
        help="Overall CPU utilization of your laptop.",
    )

    sys_mem_col.metric(
        "System Memory",
        f"{metrics['system_memory_percent']:.1f}%",
        help="Percentage of system memory currently in use.",
    )
else:
    st.warning(
        "Resource metrics unavailable. Verify that "
        "/metrics/system is implemented and responding."
    )

# --------------------------------------------------
# 5. Submit a processing job
# --------------------------------------------------

st.divider()
st.subheader("🚀 Submit a Processing Job")

with st.form("job_form"):
    workload = st.selectbox(
    "Workload Type",
    [
        "normal",
        "cpu_intensive",
        "memory_intensive",
        "mixed",
    ],
    format_func=lambda value: {
        "normal": "Normal Workload",
        "cpu_intensive": "CPU-Intensive Workload",
        "memory_intensive": "Memory-Intensive Workload",
        "mixed": "Mixed CPU + Memory Workload",
    }[value],
    )

    iterations = st.slider(
        "Iterations",
        min_value=1,
        max_value=20,
        value=1,
    )

    submitted = st.form_submit_button(
        "Run Processing Job",
        type="primary",
    )

if submitted:
    if not api_online:
        st.error("Start the backend before submitting a job.")
    else:
        try:
            with st.spinner("Processing job..."):
                response = requests.post(
                    f"{API_URL}/jobs",
                    json={
                        "workload": workload,
                        "iterations": iterations,
                    },
                    timeout=180,
                )
                response.raise_for_status()
                result = response.json()

            st.success("Job completed successfully!")
            st.json(result)
            st.rerun()

        except requests.RequestException as exc:
            st.error(f"Job submission failed: {exc}")

# --------------------------------------------------
# 6. Job history
# --------------------------------------------------

st.divider()
st.subheader("📜 Job History")

if not df.empty:
    display_columns = [
        "job_id",
        "workload",
        "iterations",
        "status",
        "duration_seconds",
        "completed_at",
    ]

    st.dataframe(
        df[display_columns],
        use_container_width=True,
        hide_index=True,
    )

    # Processing duration chart
    
    st.subheader("⏱️ Processing Duration")

    chart_df = df[["job_id", "duration_seconds"]].copy()

    chart_df["job"] = [
        f"Job {index + 1}"
        for index in range(len(chart_df))
    ]

    st.bar_chart(
        chart_df.set_index("job")["duration_seconds"]
    )

else:
    st.info(
        "No jobs found. Submit your first processing job above."
    )


# --------------------------------------------------
# Historical CPU and memory charts
# --------------------------------------------------

st.divider()
st.subheader("📈 Historical Resource Utilization")

if st.button("🔄 Refresh Metrics"):
    st.rerun()

samples = get_metrics_history()

if samples:
    metrics_df = pd.DataFrame(samples)
    metrics_df["timestamp"] = pd.to_datetime(
        metrics_df["timestamp"],
        errors="coerce",
    )
    metrics_df = (
        metrics_df.dropna(subset=["timestamp"])
        .sort_values("timestamp")
        .set_index("timestamp")
    )

    cpu_col, memory_col = st.columns(2)

    with cpu_col:
        st.markdown("**CPU Utilization (%)**")
        st.line_chart(
            metrics_df[
                ["process_cpu_percent", "system_cpu_percent"]
            ],
            height=300,
        )

    with memory_col:
        st.markdown("**Memory Utilization**")
        st.line_chart(
            metrics_df[
                ["process_memory_mb", "system_memory_percent"]
            ],
            height=300,
        )

    st.caption(
        f"Displaying {len(metrics_df)} collected samples. "
        "Backend memory is in MB; system memory is in percent."
    )
else:
    st.info(
        "No historical metrics available yet. "
        "Keep FastAPI running and wait for the collector to record samples."
    )


# --------------------------------------------------
# 7. Footer
# --------------------------------------------------

st.divider()

st.caption(
    "Prototype v0.2 | Job analytics and basic resource monitoring"
)
