
import csv
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8000"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "results"

METRIC_FIELDS = [
    "timestamp",
    "process_cpu_percent",
    "process_memory_mb",
    "system_cpu_percent",
    "system_memory_percent",
]


def utc_now():
    return datetime.now(timezone.utc)


def get_history():
    with urlopen(f"{BASE_URL}/metrics/history", timeout=5) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("samples", [])


def submit_job(result):
    result["request_started"] = utc_now().isoformat()

    try:
        payload = json.dumps({
            "workload": "cpu_intensive",
            "iterations": 10,
        }).encode("utf-8")

        request = Request(
            f"{BASE_URL}/jobs",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request, timeout=120) as response:
            result["job"] = json.loads(
                response.read().decode("utf-8")
            )

    except Exception as exc:
        result["error"] = str(exc)

    finally:
        result["request_completed"] = utc_now().isoformat()


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    experiment_start = utc_now()
    collected = {}

    job_result = {}
    job_done = threading.Event()

    def run_job():
        try:
            submit_job(job_result)
        finally:
            job_done.set()

    def collect_available_samples():
        try:
            for sample in get_history():
                timestamp = sample.get("timestamp")
                if not timestamp:
                    continue

                sample_time = datetime.fromisoformat(timestamp)

                if sample_time >= experiment_start:
                    collected[timestamp] = {
                        field: sample.get(field)
                        for field in METRIC_FIELDS
                    }
        except Exception as exc:
            print(f"Metrics collection warning: {exc}")

    print("Collecting 10 seconds of idle measurements...")
    idle_deadline = time.monotonic() + 10

    while time.monotonic() < idle_deadline:
        collect_available_samples()
        time.sleep(0.25)

    print("Submitting CPU-intensive job: 10 iterations")
    worker = threading.Thread(target=run_job, daemon=True)
    worker.start()

    while not job_done.is_set():
        collect_available_samples()
        time.sleep(0.25)

    worker.join()

    print("Collecting 10 seconds of post-job measurements...")
    post_deadline = time.monotonic() + 10

    while time.monotonic() < post_deadline:
        collect_available_samples()
        time.sleep(0.25)

    request_started = datetime.fromisoformat(
        job_result["request_started"]
    )
    request_completed = datetime.fromisoformat(
        job_result["request_completed"]
    )

    rows = []
    for sample in collected.values():
        sample_time = datetime.fromisoformat(sample["timestamp"])

        if sample_time < request_started:
            phase = "idle_before_job"
        elif sample_time <= request_completed:
            phase = "job_request_in_progress"
        else:
            phase = "after_job"

        rows.append({**sample, "phase": phase})

    rows.sort(key=lambda row: row["timestamp"])

    csv_path = OUTPUT_DIR / "cpu_coordinated_2.csv"
    fields = METRIC_FIELDS + ["phase"]

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    json_path = OUTPUT_DIR / "cpu_coordinated_2_job.json"
    json_path.write_text(
        json.dumps(job_result, indent=2),
        encoding="utf-8",
    )

    print("\nExperiment finished.")
    print(f"Samples saved: {len(rows)}")
    print(f"Metrics CSV: {csv_path}")
    print(f"Job result: {json_path}")

    if "job" in job_result:
        print("\nJob response:")
        print(json.dumps(job_result["job"], indent=2))
    else:
        print("\nJob request failed:")
        print(job_result.get("error", "Unknown error"))


if __name__ == "__main__":
    main()
