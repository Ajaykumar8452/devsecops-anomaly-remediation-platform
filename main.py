import os
import time
import uuid
from datetime import datetime, timezone
import psutil
import threading
from collections import deque
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="Data Processing and Job Analytics Platform",
    version="0.2.0",
)

process = psutil.Process(os.getpid())

# Keep the most recent 3600 samples (approximately one hour).
metrics_history = deque(maxlen=3600)
metrics_lock = threading.Lock()


def collect_metrics():
    while True:
        timestamp = datetime.now(timezone.utc).isoformat()

        try:
            sample = {
                "timestamp": timestamp,
                "process_cpu_percent": process.cpu_percent(),
                "process_memory_mb": round(
                    process.memory_info().rss / (1024 * 1024), 2
                ),
                "system_cpu_percent": psutil.cpu_percent(),
                "system_memory_percent": psutil.virtual_memory().percent,
            }

            with metrics_lock:
                metrics_history.append(sample)

        except (psutil.Error, OSError):
            pass

        time.sleep(1)


metrics_thread = threading.Thread(
    target=collect_metrics,
    daemon=True,
    name="metrics-collector",
)
metrics_thread.start()


@app.get("/metrics/history")
def get_metrics_history():
    with metrics_lock:
        return {
            "count": len(metrics_history),
            "samples": list(metrics_history),
        }

jobs = {}


class JobRequest(BaseModel):
    workload: str = Field(
        default="normal",
        pattern="^(normal|cpu_intensive|memory_intensive|mixed)$",
    )
    iterations: int = Field(default=1, ge=1, le=10)


@app.get("/")
def home():
    return {
        "application": "Data Processing and Job Analytics Platform",
        "status": "running",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/metrics/system")
def system_metrics():
    return {
        "process_cpu_percent": process.cpu_percent(interval=0.1),
        "process_memory_mb": round(
            process.memory_info().rss / (1024 * 1024), 2
        ),
        "system_cpu_percent": psutil.cpu_percent(interval=0.1),
        "system_memory_percent": psutil.virtual_memory().percent,
    }


@app.post("/jobs")
def create_job(request: JobRequest):
    job_id = str(uuid.uuid4())
    started = time.perf_counter()
    checksum = 0
    memory_data = None

    try:
        for _ in range(request.iterations):
            if request.workload == "normal":
                operations = 100_000
            elif request.workload == "cpu_intensive":
                operations = 2_000_000
            elif request.workload == "memory_intensive":
                operations = 500_000
            else:  # mixed
                operations = 1_000_000

            # CPU processing
            for number in range(operations):
                checksum = (checksum + number * number) % 1_000_003

            # Allocate a bounded amount of memory for the memory/mixed tests.
            if request.workload in ("memory_intensive", "mixed"):
                # At most approximately 16 MB per iteration.
                memory_data = bytearray(16 * 1024 * 1024)
                memory_data[0] = 1
                memory_data[-1] = 1
                del memory_data

        duration = time.perf_counter() - started

        job = {
            "job_id": job_id,
            "workload": request.workload,
            "iterations": request.iterations,
            "status": "completed",
            "duration_seconds": round(duration, 4),
            "result_checksum": checksum,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        jobs[job_id] = job
        return job

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Job processing failed: {type(exc).__name__}",
        ) from exc


@app.get("/jobs")
def list_jobs():
    return {"count": len(jobs), "jobs": list(jobs.values())}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]
