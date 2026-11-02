# Data Processing and Job Analytics Platform

This academic project collects application and host metrics, runs processing jobs, detects sustained anomalies, persists alert lifecycles, and presents operational information through a Streamlit control center. Prometheus and Grafana provide time-series collection and dashboards. Kubernetes deployment and automated remediation remain future work; the current application does not restart, scale, or otherwise modify workloads.

## Objectives and current scope

- Monitor the FastAPI backend process, the host metrics visible to that process, and HTTP traffic received by the backend.
- Detect persistent anomalies across six independently configured signals.
- Persist alert records, evaluator state, and lifecycle events in SQLite.
- Provide job submission/history and anomaly/alert management through Streamlit.
- Export existing application metrics to Prometheus and provision Grafana dashboards from repository configuration.

Backend process CPU and RSS are process measurements. System CPU and memory are operating-system measurements visible to the backend. None of these represent Kubernetes Pod or Deployment metrics.

## Architecture

```text
Browser ──> Streamlit dashboard :8501 ──HTTP/JSON──> FastAPI backend :8000
   │                                                ├── metrics collector/evaluator
   └──────────────> Grafana UI :3000                └── SQLite alert database
                              │
                              └── Prometheus datasource :9090
Prometheus ──scrapes backend:8000/metrics──> FastAPI
```

Docker Compose runs four services on its default private network:

| Service | Responsibility | Local URL |
|---|---|---|
| `backend` | FastAPI APIs, metrics collection, anomaly evaluation, jobs, and SQLite alert persistence | [http://127.0.0.1:8000](http://127.0.0.1:8000) |
| `dashboard` | Seven-page Streamlit application control center | [http://127.0.0.1:8501](http://127.0.0.1:8501) |
| `prometheus` | Scrapes and retains application time series | [http://127.0.0.1:9090](http://127.0.0.1:9090) |
| `grafana` | Provisioned dashboards using Prometheus as its default datasource | [http://127.0.0.1:3000](http://127.0.0.1:3000) |

Published ports are bound to loopback for local development. Prometheus scrapes the backend using Compose DNS (`backend:8000`), and Grafana queries Prometheus using `http://prometheus:9090`. The Streamlit process checks Grafana through `http://grafana:3000`; its dashboard links use the browser-facing `GRAFANA_BASE_URL` instead.

Without Docker, run FastAPI and Streamlit as separate local processes. Prometheus and Grafana are optional for that mode.

## Application and anomaly detection

FastAPI is implemented in `main.py`; shared anomaly policy, state-machine, SQLite, and Prometheus code is in `core/`. `application/` contains the Streamlit entry point, API client, shared UI components, and page modules. The application collects backend process CPU/RSS, system CPU/memory, HTTP request counts and durations, job outcomes and durations, and application/evaluator health signals.

The six anomaly signals are:

1. Backend process CPU utilization.
2. Backend process resident memory (RSS).
3. System memory utilization.
4. Application health.
5. HTTP 5xx error rate.
6. Average HTTP response latency.

Each signal has independent policy and evaluator state. Anomalies pass through `NORMAL`, `PENDING`, `CONFIRMED`, `RECOVERING`, and `RESOLVED`; stale or missing metric data is represented as `UNKNOWN`. The verified CPU policy remains at 80% for 60 seconds to confirm and below 70% for 30 seconds to recover. New non-CPU policies default to observation mode. See [docs/ANOMALY_DETECTION.md](docs/ANOMALY_DETECTION.md) for policy defaults and configuration variables.

Confirmed alerts, lifecycle events, per-signal evaluator state, and restart-recovery information are stored in SQLite. Job history and the backend's short metrics history are process-local. Prometheus stores scraped time series separately in its own TSDB volume.

## Prometheus metrics

The backend exposes Prometheus exposition data at `GET /metrics`. It reuses the existing collector and HTTP middleware rather than running another system-metrics poller or HTTP instrumentation layer. The `/metrics` scrape is excluded from business-request and anomaly accounting. Request labels use route templates and bounded methods/status classes; job IDs and alert IDs are not labels.

The 12 metric families are:

- `platform_backend_process_cpu_percent` and `platform_backend_process_resident_memory_bytes`
- `platform_system_cpu_percent` and `platform_system_memory_utilization_percent`
- `platform_http_requests_total`, `platform_http_request_duration_seconds`, and `platform_http_requests_in_flight`
- `platform_http_5xx_error_rate_percent` and `platform_http_response_latency_ms`
- `platform_anomaly_state`
- `platform_jobs_total` and `platform_job_duration_seconds`

The scrape configuration is [monitoring/prometheus/prometheus.yml](monitoring/prometheus/prometheus.yml): a 15-second scrape interval, 10-second timeout, and the `backend:8000/metrics` target.

## Grafana dashboards

Grafana provisioning is in `monitoring/grafana/provisioning/`, and dashboard JSON is in `monitoring/grafana/dashboards/`. Four dashboards are loaded automatically:

- **Application Overview** — backend process and system metrics, HTTP rate, in-flight requests, anomaly count, and scrape health.
- **HTTP Performance** — request rates, status classes, 5xx rate, latency percentiles, and trends.
- **Anomaly Monitoring** — signal states and confirmed, pending, recovering, and unknown counts.
- **Job Analytics** — job counts/rates by workload and duration percentiles.

## Environment configuration

`.env.example` is a reference for non-secret local settings and is not automatically loaded by Python. For Compose, it is optional; Docker Compose reads a root `.env` file for variable substitution and the backend/dashboard can also load it. Copy it if you need to change the dashboard's browser-facing Grafana URL or other documented settings:

```powershell
Copy-Item .env.example .env
```

Compose requires a local Grafana credential file. Create it from the placeholder example, then replace the placeholder with a unique, strong password before starting the stack:

```powershell
Copy-Item monitoring/grafana/grafana.env.example .env.grafana
notepad .env.grafana
```

The ignored `.env.grafana` file provides `GF_SECURITY_ADMIN_USER` and `GF_SECURITY_ADMIN_PASSWORD` to Grafana. Never commit `.env`, `.env.grafana`, or actual credentials. Only the placeholder template belongs in Git. The Grafana service uses `GF_SERVER_ROOT_URL` for the browser-facing URL; Streamlit uses `GRAFANA_BASE_URL` for dashboard links and `GRAFANA_INTERNAL_URL=http://grafana:3000` for its internal health check. If users open the dashboard from another machine, configure `GRAFANA_BASE_URL` to an address reachable by their browser; the internal Compose URL remains unchanged.

## Run locally without Docker

Python 3.13 is the validated project environment. Create a virtual environment and install the root requirements:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start FastAPI from the repository root:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

In another terminal, start Streamlit:

```powershell
$env:ANOMALY_DASHBOARD_API_URL = "http://127.0.0.1:8000"
python -m streamlit run application/dashboard.py --server.address 127.0.0.1 --server.port 8501
```

The default local SQLite path is `data/alerts.db`; `ALERT_DATABASE_PATH` can select a different path. Avoid pointing tests or disposable runs at production data.

## Run with Docker Compose

Install Docker Desktop (Linux containers) and the Docker Compose plugin. First create `.env.grafana` using the instructions above. Then, from the repository root:

```powershell
docker compose config
docker compose build
docker compose up -d
docker compose ps
```

The URLs are listed in the architecture table. FastAPI documentation is at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs); liveness and readiness are at `/livez` and `/readyz`. The local Prometheus UI is available at port 9090, and the backend metrics endpoint is at `http://127.0.0.1:8000/metrics` on loopback; Prometheus itself scrapes the backend over the Compose network.

### Persistent data

Compose uses separate named volumes:

- `alert_data` stores `/app/data/alerts.db` for persistent alerts and evaluator state.
- `prometheus_data` stores Prometheus TSDB data, with a seven-day retention setting.
- `grafana_data` stores Grafana application state.

The local `data/` directory is mounted read-only as a seed source. If the SQLite volume is empty on first startup, the backend entrypoint copies a consistent snapshot into it; an existing volume database is not replaced. Provisioning files and dashboard definitions are read-only bind mounts. `docker compose down` preserves named volumes. Do not use `docker compose down -v` unless intentionally deleting all persistent service data.

Useful commands:

```powershell
docker compose logs -f backend dashboard prometheus grafana
docker compose restart backend dashboard
docker compose stop
```

The backend, dashboard, Prometheus, and Grafana are loopback-bound for local development. Do not treat this Compose configuration as a production deployment.

## API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Compatibility health response |
| `GET /livez` | Process liveness |
| `GET /readyz` | Cached readiness of critical components |
| `GET /metrics` | Prometheus exposition endpoint |
| `GET /metrics/system` | Current backend process and system values |
| `GET /metrics/history` | Recent in-memory resource samples |
| `GET /metrics/http` | HTTP status, latency, and recent-request metrics |
| `GET /anomalies` | Legacy anomaly response |
| `GET /anomalies/state` | State and policy for all six signals |
| `GET /anomalies/history` | Persistent alert history |
| `GET /anomalies/active` | Active alerts |
| `GET /anomalies/events` | Alert lifecycle events |
| `POST /jobs` | Run a processing workload synchronously |
| `GET /jobs` | In-memory job history |
| `GET /jobs/{job_id}` | Retrieve a job from the current backend process |

## Dashboard and testing

The Streamlit sidebar contains Overview, Infrastructure Monitoring, Anomaly Detection, Job Management, Remediation Center, Audit History, and Grafana Integration. Anomaly and HTTP monitoring refresh every three seconds; alert timestamps are displayed in Indian Standard Time. The remediation page is a non-functional foundation only: there are no remediation actions or approval controls.

Run the test suite from the repository root:

```powershell
python -m unittest discover -s tests -v
```

Tests use temporary SQLite databases and local fixture APIs. On some Windows environments, the Streamlit `AppTest` render tests can stall during asyncio/socket initialization. If that happens, report those render tests as blocked rather than passed; run the backend tests separately and investigate the environment without deleting or weakening the tests.

## Implementation status

**Implemented:** FastAPI metrics collection and Prometheus instrumentation; six-signal persistent anomaly detection; SQLite alert lifecycle and restart recovery; readiness/liveness endpoints; Streamlit control center and job workflows; Prometheus Compose scraping; Grafana datasource and dashboard provisioning.

**Not implemented:** Kubernetes deployment/integration and anomaly-driven remediation. No workload restart, scaling, or other Kubernetes operation is performed. Job history is process-local and is lost when FastAPI restarts.
