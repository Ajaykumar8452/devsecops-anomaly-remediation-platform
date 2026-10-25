import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="Data Processing and Job Analytics Platform",
    description="A workload-driven application for anomaly detection research.",
    version="0.1.0",
)

jobs = {}


class JobRequest(BaseModel):
    workload: str = Field(
        default="normal",
        pattern="^(normal|cpu_intensive)$",
    )
    iterations: int = Field(default=1, ge=1, le=20)


@app.get("/")
def home():
    return {
        "application": "Data Processing and Job Analytics Platform",
        "status": "running",
        "utc_time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/jobs")
def create_job(request: JobRequest):
    job_id = str(uuid.uuid4())
    started = time.perf_counter()

    # A deterministic, configurable computational workload.
    # This runs synchronously in the API process for our first test.
    result = 0
    operations = 100_000 if request.workload == "normal" else 2_000_000

    for _ in range(request.iterations):
        for number in range(operations):
            result = (result + number * number) % 1_000_003

    duration = time.perf_counter() - started

    job = {
        "job_id": job_id,
        "workload": request.workload,
        "iterations": request.iterations,
        "status": "completed",
        "duration_seconds": round(duration, 4),
        "result_checksum": result,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    jobs[job_id] = job
    return job


@app.get("/jobs")
def list_jobs():
    return {"count": len(jobs), "jobs": list(jobs.values())}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]
