# DevSecOps Platform with Anomaly-Driven Automated Remediation for Kubernetes Applications

**Application:** Data Processing and Job Analytics Platform

This academic project currently provides a FastAPI service for local metrics, job execution, multi-signal anomaly detection and persistent alert history, together with a Streamlit application control center. The title describes the intended project direction; Kubernetes remediation is planned and is not implemented.

## Architecture

```text
Streamlit control center (application/)
        │ HTTP / JSON
        ▼
FastAPI service (main.py)
  ├── metrics and job endpoints
  ├── anomaly evaluator and health watchdog
  └── core/ policies, state machine and SQLite persistence
        │
        └── data/alerts.db (local runtime data; ignored by Git)

Experiments: experiments/scripts/ → experiments/results/
Tests:       tests/
```

The backend samples FastAPI process CPU/RSS, host CPU/memory and HTTP request metrics. It evaluates six signals: backend process CPU, backend process RSS, host system memory utilization, application internal health, HTTP 5xx rate and average response latency. Process metrics describe the FastAPI process; host metrics are system-wide and are not Kubernetes Pod or Deployment metrics.

The evaluator stores per-signal state, alert lifecycle and event history in SQLite. The existing CPU policy remains enabled with its verified behavior. Other signal policies default to observation mode and can be configured through the environment variables documented in [docs/ANOMALY_DETECTION.md](docs/ANOMALY_DETECTION.md).

## Technology stack

- Python 3.13 (the project environment used for validation)
- FastAPI and Uvicorn
- Streamlit
- pandas and requests
- psutil
- SQLite
- Python `unittest` for automated tests

No Docker, Kubernetes, Prometheus or Grafana deployment is included in the repository. The dashboard can link to an externally provided Grafana instance when configured.

## Repository structure

```text
application/                 Streamlit shell, API client, shared UI and seven pages
core/                        Anomaly policies, state machine and SQLite persistence
data/                         Runtime database location; database files are ignored
docs/                         Technical documentation
experiments/scripts/          Metric and workload experiment recorders
experiments/results/          Preserved CSV/JSON experiment outputs
archive/backups/              Preserved historical backend source snapshots
archive/test-artifacts/       Preserved interrupted test-run artifacts (ignored)
tests/                        Unit, integration and dashboard rendering tests
main.py                       Root FastAPI application entry point
requirements.txt              Runtime and dashboard dependencies
.env.example                  Optional local endpoint configuration reference
```

## Installation

From the project root, create and activate a virtual environment, then install the declared dependencies:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If the environment is already created, activate it and skip the first command. The application reads environment variables from the process environment; `.env.example` is a reference file and is not automatically loaded.

## Start FastAPI

Run in a terminal from the repository root:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

For development reload, add `--reload`. The default SQLite database is `data/alerts.db`. `ALERT_DATABASE_PATH` may override the path when intentionally configured; do not point tests or disposable runs at the production data file.

## Start Streamlit

Run in a second terminal from the repository root:

```powershell
$env:ANOMALY_DASHBOARD_API_URL = "http://127.0.0.1:8000"
python -m streamlit run application/dashboard.py --server.address 127.0.0.1 --server.port 8501
```

Open <http://127.0.0.1:8501>. The FastAPI OpenAPI page is at <http://127.0.0.1:8000/docs>.

Optional Grafana integration uses `GRAFANA_BASE_URL`. `GRAFANA_DASHBOARD_URL` can point directly to a dashboard; otherwise the base URL is linked. Grafana is not required for Streamlit to run.

## API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Compatibility health response |
| `GET /livez` | Process liveness |
| `GET /readyz` | Cached readiness status for critical components |
| `GET /metrics/system` | Current backend process and host resource values |
| `GET /metrics/history` | In-memory recent resource samples |
| `GET /metrics/http` | HTTP status, latency and recent-request metrics |
| `GET /anomalies` | Legacy anomaly response |
| `GET /anomalies/state` | Current state and policy for all six signals |
| `GET /anomalies/history` | Persistent alert history |
| `GET /anomalies/active` | Active alerts |
| `GET /anomalies/events` | Alert lifecycle events |
| `POST /jobs` | Run a processing workload synchronously |
| `GET /jobs` | In-memory job history |
| `GET /jobs/{job_id}` | Retrieve a job returned by the current backend process |

## Dashboard pages

The Streamlit sidebar provides Overview, Infrastructure Monitoring, Anomaly Detection, Job Management, Remediation Center, Audit History and Grafana Integration. Anomaly and HTTP monitoring fragments refresh every three seconds. Alert timestamps are displayed in Indian Standard Time.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

The tests use temporary databases and local fixture APIs. Do not run experiments or workload submissions against a production service as part of routine validation.

## Current implementation status

### Implemented

- FastAPI metrics collection and HTTP request monitoring.
- Six independent anomaly signal states and the verified CPU persistence/recovery behavior.
- SQLite alert history, lifecycle events and state restoration.
- Liveness and readiness endpoints.
- Seven-page Streamlit control center, job submission/history, alert history and optional Grafana linking.
- Experiment recording scripts and preserved experiment result files.

### Planned

- Docker packaging and Compose development setup.
- Kubernetes deployment, probes, resource configuration and least-privilege integration.
- Grafana installation and infrastructure data source/dashboard provisioning.
- Anomaly-driven remediation policy and execution engine, approvals, dry-run, audit and post-action verification.

No remediation, automatic restart, scaling or Kubernetes operation is currently performed. Job history is process-local and is lost when FastAPI restarts. Metrics history is also in memory and is not a durable time-series store.
