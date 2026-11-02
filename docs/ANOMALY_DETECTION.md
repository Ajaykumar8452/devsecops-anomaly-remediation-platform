# Unified anomaly detection policy

The detection policies are centralized in `core/anomaly_policy.py`. They are read
once when FastAPI starts. Set the documented environment variables before
starting the backend to change policy values; detector code does not need to
change.

## Modes

- `enabled`: evaluates the policy and persists confirmed alerts.
- `observation`: evaluates and persists confirmed alerts, labelled as
  observation-only. It does not execute remediation or other actions.
- `disabled`: exposes the signal as disabled and creates no alerts.

All new non-CPU policies default to `observation`. These are proposed
observation defaults, not production recommendations. System memory's 90%
trigger is a configurable initial candidate, not an approved production
threshold. The existing CPU policy remains enabled with its verified values.

## Proposed startup defaults

| Signal | Target | Trigger | Recovery | Confirm | Recover | Cooldown | Mode |
|---|---|---:|---:|---:|---:|---:|---|
| Backend process CPU | `fastapi_process` | >= 80% | < 70% | 60 sec | 30 sec | 0 sec | enabled |
| Backend process RSS | `fastapi_process` | >= 80 MB | <= 72 MB | 30 sec | 30 sec | 300 sec | observation |
| System memory | `host_system` | >= 90% | <= 85% | 30 sec | 30 sec | 300 sec | observation |
| Application health | `fastapi_application` | unhealthy | healthy | 10 sec | 15 sec | 60 sec | observation |
| HTTP 5xx rate | `fastapi_http_service` | >= 10%, 5+ requests | <= 5% | 30 sec | 30 sec | 300 sec | observation |
| Average HTTP latency | `fastapi_http_service` | >= 500 ms, 5+ samples | <= 400 ms | 30 sec | 30 sec | 300 sec | observation |

The memory recovery values (90% of the trigger), HTTP recovery values, and
non-CPU timers are proposed hysteresis defaults. They are configurable and
remain observation-only until explicitly changed. Process RSS is reported in
MB; it is not Pod memory utilization. System memory is host-level psutil data.

HTTP anomaly evaluation retains the existing 60-second measurement window.
The 30-second confirmation interval is a separate condition-persistence
requirement. A signal with insufficient or stale samples is `UNKNOWN`; it does
not resolve an active alert.

Application health checks database availability, metrics collector liveness,
freshness of collected metrics, and evaluator-thread liveness. The legacy
`/health` response remains unchanged and is not used alone as the detector.
This in-process check cannot detect the whole API process being unreachable; an
external monitor is needed for that failure mode.

## HTTP health probes

- `GET /health` keeps its legacy `{"status":"healthy"}` response.
- `GET /livez` returns `200` with `{"status":"alive"}` when FastAPI can serve
  the request. It deliberately does not query SQLite or other dependencies.
- `GET /readyz` returns a cached readiness snapshot and `200` only when SQLite,
  fresh metrics collection, the anomaly evaluator heartbeat, and the application
  health watchdog are healthy. Otherwise it returns `503` with per-component
  status. A background readiness monitor refreshes the cache once per second;
  the endpoint returns not-ready if that snapshot is older than five seconds.
  SQLite probes use a one-second connection/busy timeout and do not run on each
  HTTP request.

The Streamlit dashboard uses `/livez` for backend connectivity and displays
`/readyz` readiness separately. These probes do not inspect or change anomaly
state and do not perform remediation.

## Environment variables

Policy variables are applied at process startup. The dashboard does not load
these settings independently; it reads policy values from the API.

| Policy | Mode | Trigger | Recovery | Confirm seconds | Recover seconds | Cooldown seconds |
|---|---|---|---|---|---|---|
| CPU | `ANOMALY_CPU_MODE` | `ANOMALY_CPU_TRIGGER_PERCENT` | `ANOMALY_CPU_RECOVERY_PERCENT` | `ANOMALY_CPU_PERSISTENCE_SECONDS` | `ANOMALY_CPU_RECOVERY_SECONDS` | `ANOMALY_CPU_COOLDOWN_SECONDS` |
| Process RSS | `ANOMALY_PROCESS_RSS_MODE` | `ANOMALY_PROCESS_RSS_TRIGGER_MB` | `ANOMALY_PROCESS_RSS_RECOVERY_MB` | `ANOMALY_PROCESS_RSS_PERSISTENCE_SECONDS` | `ANOMALY_PROCESS_RSS_RECOVERY_SECONDS` | `ANOMALY_PROCESS_RSS_COOLDOWN_SECONDS` |
| System memory | `ANOMALY_SYSTEM_MEMORY_MODE` | `ANOMALY_SYSTEM_MEMORY_TRIGGER_PERCENT` | `ANOMALY_SYSTEM_MEMORY_RECOVERY_PERCENT` | `ANOMALY_SYSTEM_MEMORY_PERSISTENCE_SECONDS` | `ANOMALY_SYSTEM_MEMORY_RECOVERY_SECONDS` | `ANOMALY_SYSTEM_MEMORY_COOLDOWN_SECONDS` |
| Application health | `ANOMALY_HEALTH_MODE` | unhealthy boolean | healthy boolean | `ANOMALY_HEALTH_PERSISTENCE_SECONDS` | `ANOMALY_HEALTH_RECOVERY_SECONDS` | `ANOMALY_HEALTH_COOLDOWN_SECONDS` |
| HTTP 5xx | `ANOMALY_HTTP_5XX_MODE` | `ANOMALY_HTTP_5XX_TRIGGER_PERCENT` | `ANOMALY_HTTP_5XX_RECOVERY_PERCENT` | `ANOMALY_HTTP_5XX_PERSISTENCE_SECONDS` | `ANOMALY_HTTP_5XX_RECOVERY_SECONDS` | `ANOMALY_HTTP_5XX_COOLDOWN_SECONDS` |
| HTTP latency | `ANOMALY_HTTP_LATENCY_MODE` | `ANOMALY_HTTP_LATENCY_TRIGGER_MS` | `ANOMALY_HTTP_LATENCY_RECOVERY_MS` | `ANOMALY_HTTP_LATENCY_PERSISTENCE_SECONDS` | `ANOMALY_HTTP_LATENCY_RECOVERY_SECONDS` | `ANOMALY_HTTP_LATENCY_COOLDOWN_SECONDS` |

Additional sample settings are `ANOMALY_HTTP_5XX_MIN_SAMPLES`,
`ANOMALY_HTTP_LATENCY_MIN_SAMPLES`, and the policy-specific
`*_WINDOW_SECONDS` / `*_MAX_SAMPLE_AGE_SECONDS` values. Modes accept
`disabled`, `observation`, or `enabled`.

## Scope

The current engine observes this FastAPI process, the host system, and HTTP
requests received by this FastAPI instance. It does not read Kubernetes Pod or
Deployment metrics and does not perform restarts, scaling, remediation, or
other workload actions.
