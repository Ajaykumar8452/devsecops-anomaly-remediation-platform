
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

API_URL = "http://127.0.0.1:8000/metrics/history"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "results"

FIELDS = [
    "timestamp",
    "process_cpu_percent",
    "process_memory_mb",
    "system_cpu_percent",
    "system_memory_percent",
]


def get_samples():
    with urlopen(API_URL, timeout=5) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("samples", [])


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "baseline_idle"
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 120

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"{label}.csv"

    start_time = datetime.now(timezone.utc)
    start_iso = start_time.isoformat()
    collected = {}
    deadline = time.monotonic() + duration

    print(f"Experiment: {label}")
    print(f"Duration: {duration} seconds")
    print(f"Started at UTC: {start_iso}")
    print("Recording metrics. Keep the backend running...")

    while time.monotonic() < deadline:
        try:
            for sample in get_samples():
                timestamp = sample.get("timestamp")
                if not timestamp:
                    continue

                sample_time = datetime.fromisoformat(timestamp)
                if sample_time >= start_time:
                    collected[timestamp] = {
                        field: sample.get(field) for field in FIELDS
                    }

        except Exception as exc:
            print(f"Metrics read failed: {exc}")

        time.sleep(1)

    with output_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(
            sorted(collected.values(), key=lambda row: row["timestamp"])
        )

    print(f"Finished. Samples saved: {len(collected)}")
    print(f"CSV file: {output_file}")


if __name__ == "__main__":
    main()
