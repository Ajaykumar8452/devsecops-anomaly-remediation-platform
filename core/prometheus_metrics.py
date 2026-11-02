"""Prometheus metrics backed by the application's existing data paths.

Anomaly state values: NORMAL=0, PENDING=1, CONFIRMED=2, RECOVERING=3,
RESOLVED=4, UNKNOWN=5. The state label is the readable form; the sample value
is the documented numeric code.
"""

import threading

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


# A private registry prevents default process/platform collectors from
# duplicating the application's psutil-based process measurements.
REGISTRY = CollectorRegistry(auto_describe=True)

backend_process_cpu_percent = Gauge(
    "platform_backend_process_cpu_percent",
    "CPU utilization of the FastAPI backend process, measured by psutil.",
    registry=REGISTRY,
)
backend_process_resident_memory_bytes = Gauge(
    "platform_backend_process_resident_memory_bytes",
    "Resident memory of the FastAPI backend process in bytes, measured by psutil.",
    registry=REGISTRY,
)
system_cpu_percent = Gauge(
    "platform_system_cpu_percent",
    "System CPU utilization visible to the backend process environment, measured by psutil.",
    registry=REGISTRY,
)
system_memory_utilization_percent = Gauge(
    "platform_system_memory_utilization_percent",
    "System memory utilization visible to the backend process environment, measured by psutil.",
    registry=REGISTRY,
)

http_requests_total = Counter(
    "platform_http_requests_total",
    "Completed business HTTP requests handled by the FastAPI application.",
    ("method", "route", "status_class"),
    registry=REGISTRY,
)
http_request_duration_seconds = Histogram(
    "platform_http_request_duration_seconds",
    "Business HTTP request duration in seconds.",
    ("method", "route"),
    # Includes useful boundaries around the application's 500 ms candidate.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)
http_requests_in_flight = Gauge(
    "platform_http_requests_in_flight",
    "Business HTTP requests currently being handled.",
    registry=REGISTRY,
)
http_5xx_error_rate_percent = Gauge(
    "platform_http_5xx_error_rate_percent",
    "Current HTTP 5xx rate in percent from the anomaly evaluator window; NaN means unknown.",
    registry=REGISTRY,
)
http_5xx_error_rate_percent.set(float("nan"))
http_response_latency_ms = Gauge(
    "platform_http_response_latency_ms",
    "Current mean response latency in milliseconds from the anomaly evaluator window; NaN means unknown.",
    registry=REGISTRY,
)
http_response_latency_ms.set(float("nan"))
anomaly_state = Gauge(
    "platform_anomaly_state",
    "Current anomaly lifecycle state code; see module documentation for state values.",
    ("signal", "target", "state"),
    registry=REGISTRY,
)
jobs_total = Counter(
    "platform_jobs_total",
    "Job execution outcomes by bounded workload and status.",
    ("workload", "status"),
    registry=REGISTRY,
)
job_duration_seconds = Histogram(
    "platform_job_duration_seconds",
    "Successful job execution duration in seconds.",
    ("workload",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    registry=REGISTRY,
)

ANOMALY_STATE_CODES = {
    "NORMAL": 0,
    "PENDING": 1,
    "CONFIRMED": 2,
    "RECOVERING": 3,
    "RESOLVED": 4,
    "UNKNOWN": 5,
}
HTTP_METHODS = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
)
JOB_WORKLOADS = frozenset(
    {"normal", "cpu_intensive", "memory_intensive", "mixed"}
)
JOB_STATUSES = frozenset({"completed", "failed"})
ANOMALY_IDENTITIES = frozenset({
    ("backend_cpu_percent", "fastapi_process"),
    ("backend_process_memory_mb", "fastapi_process"),
    ("system_memory_percent", "host_system"),
    ("application_health", "fastapi_application"),
    ("http_5xx_error_rate_percent", "fastapi_http_service"),
    ("average_latency_ms", "fastapi_http_service"),
})

_state_lock = threading.Lock()
_current_anomaly_labels = {}


def normalize_method(method):
    method = str(method).upper()
    return method if method in HTTP_METHODS else "OTHER"


def status_class(status_code):
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return "other"
    if 100 <= code <= 599:
        return f"{code // 100}xx"
    return "other"


def route_template(request):
    """Return the matched FastAPI route template, never a raw request path."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if isinstance(template, str) and template.startswith("/") else "unmatched"


def update_collector_gauges(sample, *, process_rss_bytes=None):
    """Update gauges from one already-collected metrics-history sample."""
    if sample.get("process_cpu_percent") is not None:
        backend_process_cpu_percent.set(sample["process_cpu_percent"])
    if process_rss_bytes is None and sample.get("process_memory_mb") is not None:
        process_rss_bytes = float(sample["process_memory_mb"]) * 1024 * 1024
    if process_rss_bytes is not None:
        backend_process_resident_memory_bytes.set(process_rss_bytes)
    if sample.get("system_cpu_percent") is not None:
        system_cpu_percent.set(sample["system_cpu_percent"])
    if sample.get("system_memory_percent") is not None:
        system_memory_utilization_percent.set(sample["system_memory_percent"])


def update_http_anomaly_gauges(observations):
    """Publish values already derived by the existing anomaly evaluator."""
    for signal, value, _sample_time, _reason in observations:
        if signal == "http_5xx_error_rate_percent":
            http_5xx_error_rate_percent.set(float("nan") if value is None else value)
        elif signal == "average_latency_ms":
            http_response_latency_ms.set(float("nan") if value is None else value)


def update_anomaly_state(state):
    """Keep exactly one state series for each fixed signal/target identity."""
    lifecycle = state.get("status", "NORMAL")
    if state.get("metric_status") == "unknown":
        lifecycle = "UNKNOWN"
    if lifecycle not in ANOMALY_STATE_CODES:
        lifecycle = "UNKNOWN"
    signal = str(state.get("signal", "unknown"))
    target = str(state.get("target_id", "unknown"))
    key = (signal, target)
    if key not in ANOMALY_IDENTITIES:
        return
    labels = (signal, target, lifecycle)
    with _state_lock:
        previous = _current_anomaly_labels.get(key)
        if previous and previous != labels:
            anomaly_state.remove(*previous)
        anomaly_state.labels(*labels).set(ANOMALY_STATE_CODES[lifecycle])
        _current_anomaly_labels[key] = labels


def record_job(workload, status, duration_seconds=None):
    workload = workload if workload in JOB_WORKLOADS else "other"
    status = status if status in JOB_STATUSES else "failed"
    jobs_total.labels(workload, status).inc()
    if status == "completed" and duration_seconds is not None:
        job_duration_seconds.labels(workload).observe(duration_seconds)
