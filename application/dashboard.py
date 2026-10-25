
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
st.caption("Submit processing jobs, monitor performance, and inspect results.")

# Check backend availability
try:
    health = requests.get(f"{API_URL}/health", timeout=3)
    api_online = health.status_code == 200
except requests.RequestException:
    api_online = False

if api_online:
    st.success("Backend API: Connected")
else:
    st.error("Backend API is unavailable. Start FastAPI on port 8000.")

# Fetch job history
jobs = []
if api_online:
    try:
        response = requests.get(f"{API_URL}/jobs", timeout=5)
        response.raise_for_status()
        jobs = response.json().get("jobs", [])
    except requests.RequestException as exc:
        st.error(f"Could not retrieve jobs: {exc}")

df = pd.DataFrame(jobs)

total = len(df)
completed = int((df["status"] == "completed").sum()) if total else 0
failed = int((df["status"] == "failed").sum()) if total else 0
avg_duration = (
    float(df["duration_seconds"].mean()) if total else 0.0
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Jobs", total)
col2.metric("Completed", completed)
col3.metric("Failed", failed)
col4.metric("Avg Duration", f"{avg_duration:.3f} s")

st.divider()

st.subheader("🚀 Submit a Processing Job")

with st.form("job_form"):
    workload = st.selectbox(
        "Workload Type",
        ["normal", "cpu_intensive"],
        format_func=lambda x: {
            "normal": "Normal Workload",
            "cpu_intensive": "CPU-Intensive Workload",
        }[x],
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

st.divider()

st.subheader("📋 Job History")

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

    st.subheader("⏱️ Processing Duration")
    chart_df = df[["job_id", "duration_seconds"]].copy()
    chart_df["job"] = [
        f"Job {i + 1}" for i in range(len(chart_df))
    ]
    st.bar_chart(
        chart_df.set_index("job")["duration_seconds"]
    )
else:
    st.info("No jobs found. Submit your first job above.")

st.caption(
    "Prototype v0.1 | CPU and memory monitoring will be added "
    "in a later milestone."
)
