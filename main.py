import os
import time
import uuid
from datetime import datetime, timezone
import psutil
import threading
import logging
import statistics
import math
import numbers
from collections import deque
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from collections import Counter
from fastapi import Request
from fastapi import Query
from core.database import (
    AlertDatabaseError,
    check_database,
    get_alert_events,
    get_active_alerts,
    get_all_alerts,
    load_anomaly_states,
    initialize_database,
    persist_engine_updates,
)
from core.anomaly_engine import (
    advance_state,
    initial_state,
    mark_unknown,
    parse_time,
    restore_states,
)
from core.anomaly_policy import POLICIES, condition_for, public_policy
from core.prometheus_metrics import (
    REGISTRY as PROMETHEUS_REGISTRY,
    http_request_duration_seconds as prometheus_http_request_duration_seconds,
    http_requests_in_flight as prometheus_http_requests_in_flight,
    http_requests_total as prometheus_http_requests_total,
    normalize_method as normalize_http_method,
    record_job as record_prometheus_job,
    route_template as prometheus_route_template,
    status_class as prometheus_status_class,
    update_anomaly_state as update_prometheus_anomaly_state,
    update_collector_gauges as update_prometheus_collector_gauges,
    update_http_anomaly_gauges as update_prometheus_http_anomaly_gauges,
)

initialize_database()

app = FastAPI(
    title="Data Processing and Job Analytics Platform",
    version="0.2.0",
)

http_metrics_lock = threading.Lock()

http_metrics = {
    "total_requests": 0,
    "status_codes": Counter(),
    "endpoint_counts": Counter(),
    "total_latency_ms": 0.0,
    "recent_requests": deque(maxlen=1000),
    "in_flight_requests": 0,
}


@app.middleware("http")
async def collect_http_metrics(request: Request, call_next):
    # Avoid scrape feedback into business request and anomaly statistics.
    if request.url.path == "/metrics":
        return await call_next(request)

    started = time.perf_counter()
    endpoint = request.url.path

    with http_metrics_lock:
        http_metrics["in_flight_requests"] += 1
        prometheus_http_requests_in_flight.set(
            http_metrics["in_flight_requests"]
        )

    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response

    finally:
        latency_ms = (time.perf_counter() - started) * 1000
        timestamp = datetime.now(timezone.utc).isoformat()

        sample = {
            "timestamp": timestamp,
            "method": request.method,
            "endpoint": endpoint,
            "status_code": status_code,
            "latency_ms": round(latency_ms, 2),
        }
        method = normalize_http_method(request.method)
        route = prometheus_route_template(request)
        status = prometheus_status_class(status_code)

        with http_metrics_lock:
            http_metrics["total_requests"] += 1
            http_metrics["status_codes"][str(status_code)] += 1
            http_metrics["endpoint_counts"][endpoint] += 1
            http_metrics["total_latency_ms"] += latency_ms
            http_metrics["recent_requests"].append(sample)
            http_metrics["in_flight_requests"] -= 1
            prometheus_http_requests_total.labels(method, route, status).inc()
            prometheus_http_request_duration_seconds.labels(method, route).observe(
                latency_ms / 1000.0
            )
            prometheus_http_requests_in_flight.set(http_metrics["in_flight_requests"])

process = psutil.Process(os.getpid())

# Dedicated process object for historical CPU measurements.
metrics_process = psutil.Process(os.getpid())

# Initialize the CPU counter before collecting historical samples.
metrics_process.cpu_percent()

# Keep the most recent 3600 samples (approximately one hour).
metrics_history = deque(maxlen=3600)
metrics_lock = threading.Lock()


def collect_metrics():
    while True:
        timestamp = datetime.now(timezone.utc).isoformat()

        try:
            rss_bytes = process.memory_info().rss
            sample = {
                "timestamp": timestamp,
                "process_cpu_percent": metrics_process.cpu_percent(),
                "process_memory_mb": round(rss_bytes / (1024 * 1024), 2),
                "system_cpu_percent": psutil.cpu_percent(),
                "system_memory_percent": psutil.virtual_memory().percent,
            }
            update_prometheus_collector_gauges(
                sample, process_rss_bytes=rss_bytes
            )

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


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    """Expose the dedicated Prometheus registry without scanning app history."""
    return Response(
        content=generate_latest(PROMETHEUS_REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/metrics/http")
def get_http_metrics():
    with http_metrics_lock:
        total = http_metrics["total_requests"]

        return {
            "total_requests": total,
            "status_codes": dict(http_metrics["status_codes"]),
            "endpoint_counts": dict(http_metrics["endpoint_counts"]),
            "average_latency_ms": round(
                http_metrics["total_latency_ms"] / total, 2
            ) if total else 0.0,
            "in_flight_requests": http_metrics["in_flight_requests"],
            "recent_requests": list(http_metrics["recent_requests"]),
        }


@app.get("/metrics/history")
def get_metrics_history():
    with metrics_lock:
        return {
            "count": len(metrics_history),
            "samples": list(metrics_history),
        }

# --------------------------------------------------
# Anomaly Detection - Initial Rule-Based Version
# --------------------------------------------------

ANOMALY_THRESHOLDS = {
    "backend_cpu_percent": 80.0,
    "backend_memory_mb": 80.0,
    "requests_per_second": 20.0,
    "average_latency_ms": 500.0,
    "http_5xx_error_rate_percent": 10.0,
}


@app.get("/anomalies")
def detect_anomalies():
    now = datetime.now(timezone.utc)

    # Copy shared data while holding its respective lock.
    with metrics_lock:
        history = list(metrics_history)

    with http_metrics_lock:
        requests_history = list(
            http_metrics["recent_requests"]
        )

    findings = []

    def add_finding(
        name,
        value,
        threshold,
        unit,
        anomalous,
        detail,
    ):
        findings.append({
            "signal": name,
            "value": round(float(value), 2),
            "threshold": threshold,
            "unit": unit,
            "status": "anomaly" if anomalous else "normal",
            "detail": detail,
        })

    # 1. CPU: average of the last five historical samples.
    cpu_samples = [
        sample.get("process_cpu_percent")
        for sample in history[-5:]
        if sample.get("process_cpu_percent") is not None
    ]

    if len(cpu_samples) >= 5:
        cpu_average = sum(cpu_samples) / len(cpu_samples)

        add_finding(
            "backend_cpu_percent",
            cpu_average,
            ANOMALY_THRESHOLDS["backend_cpu_percent"],
            "%",
            cpu_average >= ANOMALY_THRESHOLDS[
                "backend_cpu_percent"
            ],
            "Average backend CPU across the last five samples.",
        )
    else:
        findings.append({
            "signal": "backend_cpu_percent",
            "value": None,
            "threshold": ANOMALY_THRESHOLDS[
                "backend_cpu_percent"
            ],
            "unit": "%",
            "status": "insufficient_data",
            "detail": "Collect at least five historical samples.",
        })

    # 2. Current backend memory.
    try:
        current_memory_mb = (
            process.memory_info().rss / (1024 * 1024)
        )

        add_finding(
            "backend_memory_mb",
            current_memory_mb,
            ANOMALY_THRESHOLDS["backend_memory_mb"],
            "MB",
            current_memory_mb >= ANOMALY_THRESHOLDS[
                "backend_memory_mb"
            ],
            "Current backend resident memory; not job peak memory.",
        )
    except (psutil.Error, OSError):
        findings.append({
            "signal": "backend_memory_mb",
            "value": None,
            "threshold": ANOMALY_THRESHOLDS[
                "backend_memory_mb"
            ],
            "unit": "MB",
            "status": "unavailable",
            "detail": "Could not read backend process memory.",
        })

    # Parse retained HTTP request timestamps.
    parsed_requests = []

    for request_sample in requests_history:
        try:
            timestamp = datetime.fromisoformat(
                request_sample["timestamp"]
            )

            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(
                    tzinfo=timezone.utc
                )

            parsed_requests.append(
                (timestamp, request_sample)
            )
        except (KeyError, TypeError, ValueError):
            continue

    # 3. Request rate in the last ten seconds.
    recent_10s = [
        sample
        for timestamp, sample in parsed_requests
        if 0 <= (now - timestamp).total_seconds() <= 10
    ]

    request_rate = len(recent_10s) / 10.0

    add_finding(
        "requests_per_second",
        request_rate,
        ANOMALY_THRESHOLDS["requests_per_second"],
        "requests/sec",
        request_rate >= ANOMALY_THRESHOLDS[
            "requests_per_second"
        ],
        "Request count in the last ten seconds divided by ten.",
    )

    # Use a 60-second window for latency and server errors.
    recent_60s = [
        sample
        for timestamp, sample in parsed_requests
        if 0 <= (now - timestamp).total_seconds() <= 60
    ]

    # 4. Average HTTP latency over the last 60 seconds.
    latencies = [
        float(sample["latency_ms"])
        for sample in recent_60s
        if sample.get("latency_ms") is not None
    ]

    if latencies:
        latency_average = sum(latencies) / len(latencies)

        add_finding(
            "average_latency_ms",
            latency_average,
            ANOMALY_THRESHOLDS["average_latency_ms"],
            "ms",
            latency_average >= ANOMALY_THRESHOLDS[
                "average_latency_ms"
            ],
            "Average latency across retained requests in the last 60 seconds.",
        )
    else:
        findings.append({
            "signal": "average_latency_ms",
            "value": None,
            "threshold": ANOMALY_THRESHOLDS[
                "average_latency_ms"
            ],
            "unit": "ms",
            "status": "insufficient_data",
            "detail": "No HTTP requests in the last 60 seconds.",
        })

    # 5. HTTP 5xx error rate over the last 60 seconds.
    server_errors = sum(
        1
        for sample in recent_60s
        if str(sample.get("status_code", "")).startswith("5")
    )

    if len(recent_60s) >= 5:
        error_rate = (
            server_errors / len(recent_60s)
        ) * 100.0

        add_finding(
            "http_5xx_error_rate_percent",
            error_rate,
            ANOMALY_THRESHOLDS[
                "http_5xx_error_rate_percent"
            ],
            "%",
            error_rate >= ANOMALY_THRESHOLDS[
                "http_5xx_error_rate_percent"
            ],
            "Percentage of retained HTTP requests returning 5xx in the last 60 seconds.",
        )
    else:
        findings.append({
            "signal": "http_5xx_error_rate_percent",
            "value": None,
            "threshold": ANOMALY_THRESHOLDS[
                "http_5xx_error_rate_percent"
            ],
            "unit": "%",
            "status": "insufficient_data",
            "detail": "At least five HTTP requests are needed in the last 60 seconds.",
        })

    anomalies = [
        finding
        for finding in findings
        if finding["status"] == "anomaly"
    ]

    return {
        "checked_at": now.isoformat(),
        "overall_status": (
            "anomaly_detected" if anomalies else "normal"
        ),
        "anomaly_count": len(anomalies),
        "checks": findings,
        "anomalies": anomalies,
        "thresholds": ANOMALY_THRESHOLDS,
    }


# --------------------------------------------------
# Persistent multi-signal anomaly evaluator
# --------------------------------------------------

CPU_POLICY = POLICIES["backend_cpu_percent"]
CPU_TRIGGER_PERCENT = CPU_POLICY.trigger_threshold
CPU_RECOVERY_PERCENT = CPU_POLICY.recovery_threshold
CPU_PERSISTENCE_SECONDS = CPU_POLICY.persistence_seconds
CPU_RECOVERY_SECONDS = CPU_POLICY.recovery_seconds

anomaly_state_lock = threading.RLock()
signal_states = {
    (policy.signal, policy.target_id): initial_state(policy.signal, policy.target_id)
    for policy in POLICIES.values()
}
cpu_anomaly_state = {
    "status": "normal",
    "pending_since": None,
    "recovery_since": None,
    "last_sample_timestamp": None,
    "active_alert_id": None,
}
cpu_alert_history = deque(maxlen=500)
health_components = {}
failed_sample_attempts = {}
evaluator_heartbeat_at = None
health_watchdog_heartbeat_at = None
cpu_evaluator_thread = None
health_watchdog_thread = None

READINESS_CHECK_INTERVAL_SECONDS = 1.0
READINESS_MAX_AGE_SECONDS = 5.0
readiness_lock = threading.Lock()
readiness_snapshot = {
    "ready": False,
    "checked_at": None,
    "components": {
        "database": False,
        "metrics_collector": False,
        "anomaly_evaluator": False,
        "health_watchdog": False,
    },
}


def _cpu_legacy_status(state):
    return {
        "NORMAL": "normal",
        "PENDING": "pending",
        "CONFIRMED": "confirmed",
        "RECOVERING": "confirmed",
        "RESOLVED": "normal",
    }.get(state.get("status"), "normal")


def _sync_legacy_cpu_state():
    state = signal_states[(CPU_POLICY.signal, CPU_POLICY.target_id)]
    cpu_anomaly_state.update({
        "status": _cpu_legacy_status(state),
        "pending_since": state.get("pending_since"),
        "recovery_since": state.get("recovery_since"),
        "last_sample_timestamp": state.get("last_processed_sample"),
        "active_alert_id": state.get("active_alert_id"),
    })


def restore_active_alert_state():
    """Restore every signal by (signal, target), including legacy alerts."""
    restored = restore_states(
        POLICIES,
        load_anomaly_states(),
        get_active_alerts(),
    )

    updates = [{"state": state, "events": []} for state in restored.values()]
    persist_engine_updates(updates)
    with anomaly_state_lock:
        signal_states.clear()
        signal_states.update(restored)
        for state in restored.values():
            update_prometheus_anomaly_state(state)
        cpu_alert_history.clear()
        cpu_alert_history.extend(get_all_alerts(limit=500))
        _sync_legacy_cpu_state()


restore_active_alert_state()


def _metric_value_is_fresh(sample_time, policy, now):
    if sample_time is None:
        return False
    return (now - sample_time).total_seconds() <= policy.max_sample_age_seconds


def _metric_value_invalid_reason(signal, value):
    """Reject malformed observations so they are surfaced as UNKNOWN."""
    if value is None:
        return "metric value missing"
    if signal == "application_health":
        return None if isinstance(value, bool) else "invalid application health value"
    if isinstance(value, bool):
        return "invalid numeric metric value"
    if not isinstance(value, numbers.Real):
        return "invalid numeric metric value"
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        return "non-finite numeric metric value"
    return None


def _process_signal_samples(samples, *, now=None):
    """Evaluate and atomically persist a batch of fresh or stale observations."""
    now = now or datetime.now(timezone.utc)
    updates = []
    candidates = []

    with anomaly_state_lock:
        for signal, value, sample_time, unknown_reason in samples:
            policy = POLICIES[signal]
            key = (policy.signal, policy.target_id)
            old = signal_states[key]

            if policy.mode == "disabled":
                if old.get("metric_status") != "disabled":
                    sample_identity = f"disabled:{signal}:{policy.target_id}"
                    if failed_sample_attempts.get(key) == sample_identity:
                        continue
                    new_state = dict(old)
                    new_state.update({
                        "metric_status": "disabled",
                        "metric_timestamp": None,
                        "observed_value": None,
                        "updated_at": now.isoformat(),
                    })
                    updates.append({"state": new_state, "events": []})
                    updates[-1]["sample_identity"] = sample_identity
                    candidates.append((key, new_state, None, None))
                continue

            invalid_reason = _metric_value_invalid_reason(signal, value)
            if (
                sample_time is None
                or invalid_reason
                or not _metric_value_is_fresh(sample_time, policy, now)
            ):
                reason = (
                    unknown_reason
                    or invalid_reason
                    or "metric missing or stale"
                )
                sample_identity = (
                    f"unknown:{reason}:{old.get('last_processed_sample')}"
                )
                if failed_sample_attempts.get(key) == sample_identity:
                    continue
                if old.get("metric_status") != "unknown" or old.get("unknown_reason") != reason:
                    new_state = mark_unknown(old, now=now, reason=reason)
                    updates.append({
                        "state": new_state,
                        "events": [],
                        "sample_identity": sample_identity,
                    })
                    candidates.append((key, new_state, None, None))
                continue

            sample_text = sample_time.isoformat()
            if sample_text == old.get("last_processed_sample"):
                continue

            triggered, recovered = condition_for(policy, value)
            previous_sample = parse_time(old.get("last_processed_sample"))
            gap_detected = (
                signal != "backend_cpu_percent"
                and previous_sample is not None
                and (sample_time - previous_sample).total_seconds()
                > policy.max_sample_age_seconds
            )
            new_state, events = advance_state(
                old,
                triggered=triggered,
                recovered=recovered,
                sample_time=sample_time,
                observed_value=value,
                policy=policy,
                gap_detected=gap_detected,
            )
            alert = next(
                (event["alert"] for event in events if event["event_type"] == "confirmed"),
                None,
            )
            resolved = next(
                (
                    {"alert_id": event["alert_id"], "resolved_at": event["resolved_at"]}
                    for event in events if event["event_type"] == "resolved"
                ),
                None,
            )
            if failed_sample_attempts.get(key) == sample_text:
                continue
            updates.append({
                "state": new_state,
                "events": events,
                "alert": alert,
                "resolve": resolved,
                "sample_identity": sample_text,
            })
            candidates.append((key, new_state, alert, resolved))

        if not updates:
            return

        try:
            persist_engine_updates(updates)
        except AlertDatabaseError:
            for update in updates:
                state = update["state"]
                key = (state["signal"], state["target_id"])
                failed_sample_attempts[key] = update.get(
                    "sample_identity",
                    state.get("last_processed_sample")
                    or f"unknown:{state.get('unknown_reason')}",
                )
            logging.getLogger(__name__).exception(
                "Could not persist anomaly state batch"
            )
            return

        for key, new_state, alert, resolved in candidates:
            signal_states[key] = new_state
            update_prometheus_anomaly_state(new_state)
            failed_sample_attempts.pop(key, None)
            if alert and alert["alert_id"] == new_state.get("active_alert_id"):
                cpu_alert_history.append(alert)
            if resolved:
                for old_alert in reversed(cpu_alert_history):
                    if old_alert["alert_id"] == resolved["alert_id"]:
                        old_alert["status"] = "resolved"
                        old_alert["resolved_at"] = resolved["resolved_at"]
                        break
        _sync_legacy_cpu_state()


def _evaluate_http_metrics(now):
    with http_metrics_lock:
        requests_history = list(http_metrics["recent_requests"])
    http_policy = POLICIES["http_5xx_error_rate_percent"]
    latency_policy = POLICIES["average_latency_ms"]

    def recent_samples(policy):
        selected = []
        for request_sample in requests_history:
            try:
                timestamp = datetime.fromisoformat(request_sample["timestamp"])
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                age = (now - timestamp).total_seconds()
                if 0 <= age <= policy.sample_window_seconds:
                    selected.append(request_sample)
            except (KeyError, TypeError, ValueError):
                continue
        return selected

    http_samples = recent_samples(http_policy)
    latency_samples = recent_samples(latency_policy)
    error_rate = None
    if len(http_samples) >= http_policy.min_samples:
        server_errors = sum(
            str(sample.get("status_code", "")).startswith("5")
            for sample in http_samples
        )
        error_rate = server_errors / len(http_samples) * 100.0

    latency_values = []
    for sample in latency_samples:
        try:
            if sample.get("latency_ms") is not None:
                latency_values.append(float(sample["latency_ms"]))
        except (TypeError, ValueError):
            continue
    average_latency = (
        statistics.fmean(latency_values)
        if len(latency_values) >= latency_policy.min_samples
        else None
    )
    sample_time = now
    return [
        (
            http_policy.signal,
            error_rate,
            sample_time if error_rate is not None else None,
            "insufficient request samples" if error_rate is None else None,
        ),
        (
            latency_policy.signal,
            average_latency,
            sample_time if average_latency is not None else None,
            "insufficient latency samples" if average_latency is None else None,
        ),
    ]


def _application_health_observation(now):
    evaluator_alive = bool(
        cpu_evaluator_thread is not None
        and cpu_evaluator_thread.is_alive()
        and evaluator_heartbeat_at is not None
        and (now - evaluator_heartbeat_at).total_seconds()
        <= POLICIES["application_health"].max_sample_age_seconds
    )
    components = {
        "database": False,
        "metrics_collector": False,
        "metrics_fresh": False,
        "evaluator": evaluator_alive,
    }
    try:
        components["database"] = check_database(timeout_seconds=1)
    except AlertDatabaseError:
        components["database"] = False

    components["metrics_collector"] = metrics_thread.is_alive()
    with metrics_lock:
        latest = dict(metrics_history[-1]) if metrics_history else None
    if latest and latest.get("timestamp"):
        try:
            latest_time = datetime.fromisoformat(latest["timestamp"])
            if latest_time.tzinfo is None:
                latest_time = latest_time.replace(tzinfo=timezone.utc)
            components["metrics_fresh"] = (
                now - latest_time
            ).total_seconds() <= POLICIES["application_health"].max_sample_age_seconds
        except (TypeError, ValueError):
            components["metrics_fresh"] = False

    healthy = all(components.values())
    health_components.clear()
    health_components.update(components)
    return healthy


def evaluate_anomalies():
    """Consume metrics and advance independent signal state machines."""
    next_http_check = 0.0
    while True:
        now = datetime.now(timezone.utc)
        observations = []
        try:
            with metrics_lock:
                latest = dict(metrics_history[-1]) if metrics_history else None

            if latest:
                sample_time = datetime.fromisoformat(latest["timestamp"])
                if sample_time.tzinfo is None:
                    sample_time = sample_time.replace(tzinfo=timezone.utc)
                observations.extend([
                    ("backend_cpu_percent", latest.get("process_cpu_percent"), sample_time, None),
                    ("backend_process_memory_mb", latest.get("process_memory_mb"), sample_time, None),
                    ("system_memory_percent", latest.get("system_memory_percent"), sample_time, None),
                ])
            else:
                observations.extend([
                    ("backend_cpu_percent", None, None, "no process metric samples"),
                    ("backend_process_memory_mb", None, None, "no process metric samples"),
                    ("system_memory_percent", None, None, "no system metric samples"),
                ])

            monotonic_now = time.monotonic()
            if monotonic_now >= next_http_check:
                http_observations = _evaluate_http_metrics(now)
                update_prometheus_http_anomaly_gauges(http_observations)
                observations.extend(http_observations)
                next_http_check = monotonic_now + 1.0

            _process_signal_samples(observations, now=now)
            global evaluator_heartbeat_at
            evaluator_heartbeat_at = datetime.now(timezone.utc)
        except (ValueError, KeyError, TypeError, psutil.Error, OSError):
            logging.getLogger(__name__).exception(
                "Could not evaluate anomaly metrics"
            )
        time.sleep(0.2)


def evaluate_application_health():
    """Monitor evaluator health from an independent thread."""
    policy = POLICIES["application_health"]
    while True:
        now = datetime.now(timezone.utc)
        try:
            healthy = _application_health_observation(now)
            _process_signal_samples(
                [(policy.signal, healthy, now, None)],
                now=now,
            )
            global health_watchdog_heartbeat_at
            health_watchdog_heartbeat_at = datetime.now(timezone.utc)
        except (ValueError, KeyError, TypeError, AlertDatabaseError, OSError):
            logging.getLogger(__name__).exception(
                "Could not evaluate application health"
            )
        time.sleep(policy.sample_window_seconds)


cpu_evaluator_thread = threading.Thread(
    target=evaluate_anomalies,
    daemon=True,
    name="anomaly-evaluator",
)
cpu_evaluator_thread.start()

health_watchdog_thread = threading.Thread(
    target=evaluate_application_health,
    daemon=True,
    name="application-health-watchdog",
)
health_watchdog_thread.start()


def _refresh_readiness_snapshot(now=None):
    """Refresh readiness outside request handling, with bounded DB checks."""
    now = now or datetime.now(timezone.utc)
    components = {
        "database": False,
        "metrics_collector": False,
        "anomaly_evaluator": False,
        "health_watchdog": False,
    }
    try:
        components["database"] = check_database(timeout_seconds=1)
    except AlertDatabaseError:
        components["database"] = False

    components["metrics_collector"] = metrics_thread.is_alive()
    with metrics_lock:
        latest = dict(metrics_history[-1]) if metrics_history else None
    if latest and latest.get("timestamp"):
        try:
            metrics_time = datetime.fromisoformat(latest["timestamp"])
            if metrics_time.tzinfo is None:
                metrics_time = metrics_time.replace(tzinfo=timezone.utc)
            metric_age = (now - metrics_time).total_seconds()
            components["metrics_collector"] = (
                components["metrics_collector"]
                and 0 <= metric_age <= POLICIES["application_health"].max_sample_age_seconds
            )
        except (TypeError, ValueError):
            components["metrics_collector"] = False
    else:
        components["metrics_collector"] = False

    evaluator_max_age = POLICIES["backend_cpu_percent"].max_sample_age_seconds
    evaluator_age = (
        (now - evaluator_heartbeat_at).total_seconds()
        if evaluator_heartbeat_at is not None else None
    )
    components["anomaly_evaluator"] = bool(
        cpu_evaluator_thread is not None
        and cpu_evaluator_thread.is_alive()
        and evaluator_age is not None
        and 0 <= evaluator_age <= evaluator_max_age
    )

    watchdog_max_age = max(
        3 * POLICIES["application_health"].sample_window_seconds,
        READINESS_CHECK_INTERVAL_SECONDS * 3,
    )
    watchdog_age = (
        (now - health_watchdog_heartbeat_at).total_seconds()
        if health_watchdog_heartbeat_at is not None else None
    )
    components["health_watchdog"] = bool(
        health_watchdog_thread is not None
        and health_watchdog_thread.is_alive()
        and watchdog_age is not None
        and 0 <= watchdog_age <= watchdog_max_age
    )

    result = {
        "ready": all(components.values()),
        "checked_at": now.isoformat(),
        "components": components,
    }
    with readiness_lock:
        readiness_snapshot.clear()
        readiness_snapshot.update(result)
    return result


def _readiness_response(now=None):
    now = now or datetime.now(timezone.utc)
    with readiness_lock:
        snapshot = {
            "ready": readiness_snapshot["ready"],
            "checked_at": readiness_snapshot["checked_at"],
            "components": dict(readiness_snapshot["components"]),
        }
    checked_at = snapshot["checked_at"]
    if checked_at:
        try:
            checked_time = datetime.fromisoformat(checked_at)
            if checked_time.tzinfo is None:
                checked_time = checked_time.replace(tzinfo=timezone.utc)
            cache_age = (now - checked_time).total_seconds()
        except (TypeError, ValueError):
            cache_age = READINESS_MAX_AGE_SECONDS + 1
    else:
        cache_age = READINESS_MAX_AGE_SECONDS + 1
    if not 0 <= cache_age <= READINESS_MAX_AGE_SECONDS:
        snapshot["ready"] = False
        snapshot["components"]["readiness_monitor"] = False
    else:
        snapshot["components"]["readiness_monitor"] = True
    snapshot["status"] = "ready" if snapshot["ready"] else "not_ready"
    return JSONResponse(
        status_code=200 if snapshot["ready"] else 503,
        content=snapshot,
    )


def monitor_readiness():
    """Maintain a cached readiness snapshot without slowing HTTP handlers."""
    while True:
        try:
            _refresh_readiness_snapshot()
        except Exception:
            logging.getLogger(__name__).exception("Could not refresh readiness status")
        time.sleep(READINESS_CHECK_INTERVAL_SECONDS)


readiness_monitor_thread = threading.Thread(
    target=monitor_readiness,
    daemon=True,
    name="readiness-monitor",
)
readiness_monitor_thread.start()


@app.get("/anomalies/state")
def get_cpu_anomaly_state():
    try:
        history = get_all_alerts(limit=500)
        active_alerts = get_active_alerts()
    except AlertDatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    with anomaly_state_lock:
        active_by_key = {}
        for alert in active_alerts:
            key = (alert["signal"], alert.get("target_id", "fastapi_process"))
            active_by_key.setdefault(key, alert)
        signals = {}
        now = datetime.now(timezone.utc)
        for signal, policy in POLICIES.items():
            state = dict(signal_states[(policy.signal, policy.target_id)])
            pending_time = parse_time(state.get("pending_since"))
            recovery_time = parse_time(state.get("recovery_since"))
            signals[signal] = {
                "signal": signal,
                "target_id": policy.target_id,
                "label": policy.label,
                "state": state["status"],
                "metric_status": state.get("metric_status", "unknown"),
                "policy_mode": policy.mode,
                "policy": public_policy(policy),
                "current_value": state.get("observed_value"),
                "metric_timestamp": state.get("metric_timestamp"),
                "pending_since": state.get("pending_since"),
                "recovery_since": state.get("recovery_since"),
                "persistence_elapsed_seconds": (
                    max(0.0, (now - pending_time).total_seconds())
                    if pending_time else 0.0
                ),
                "recovery_elapsed_seconds": (
                    max(0.0, (now - recovery_time).total_seconds())
                    if recovery_time else 0.0
                ),
                "active_alert_id": state.get("active_alert_id"),
                "active_alert": active_by_key.get((signal, policy.target_id)),
                "cooldown_until": state.get("cooldown_until"),
                "unknown_reason": state.get("unknown_reason"),
            }
            if signal == "application_health":
                signals[signal]["components"] = dict(health_components)

        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": cpu_anomaly_state["status"],
            "thresholds": {
                "trigger_percent": CPU_TRIGGER_PERCENT,
                "recovery_percent": CPU_RECOVERY_PERCENT,
                "persistence_seconds": CPU_PERSISTENCE_SECONDS,
                "recovery_seconds": CPU_RECOVERY_SECONDS,
            },
            "pending_since": cpu_anomaly_state["pending_since"],
            "recovery_since": cpu_anomaly_state["recovery_since"],
            "active_alert_id": cpu_anomaly_state["active_alert_id"],
            "alert_history": history,
            "signals": signals,
        }


@app.get("/anomalies/history")
def get_cpu_anomaly_history(limit: int = Query(default=100, ge=1, le=500)):
    try:
        return {"count": len(alerts := get_all_alerts(limit=limit)), "alerts": alerts}
    except AlertDatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/anomalies/active")
def get_active_cpu_anomalies():
    try:
        alerts = get_active_alerts()
        return {"count": len(alerts), "alerts": alerts}
    except AlertDatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/anomalies/events")
def get_anomaly_event_history(limit: int = Query(default=100, ge=1, le=1000)):
    try:
        events = get_alert_events(limit=limit)
        return {"count": len(events), "events": events}
    except AlertDatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc





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


@app.get(
    "/livez",
    summary="Process liveness probe",
    description="Confirms the FastAPI process can serve HTTP requests. This check does not query databases or other dependencies.",
)
def livez():
    return {"status": "alive"}


@app.get(
    "/readyz",
    summary="Application readiness probe",
    description="Returns a cached readiness snapshot for SQLite, metrics collection, the anomaly evaluator, and the health watchdog.",
    responses={503: {"description": "One or more required components are unavailable or the readiness snapshot is stale."}},
)
def readyz():
    return _readiness_response()


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

def measure_peak_memory(stop_event, peak_memory):
    while not stop_event.is_set():
        try:
            memory_mb = process.memory_info().rss / (1024 * 1024)

            if memory_mb > peak_memory["value"]:
                peak_memory["value"] = memory_mb

        except (psutil.Error, OSError):
            pass

        stop_event.wait(0.05)

@app.post("/jobs")
def create_job(request: JobRequest):
    job_id = str(uuid.uuid4())
    started = time.perf_counter()
    checksum = 0

    peak_memory = {
        "value": process.memory_info().rss / (1024 * 1024)
    }
    stop_event = threading.Event()

    sampler = threading.Thread(
        target=measure_peak_memory,
        args=(stop_event, peak_memory),
        daemon=True,
        name=f"peak-memory-{job_id}",
    )

    try:
        sampler.start()

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
                checksum = (
                    checksum + number * number
                ) % 1_000_003

            # Allocate bounded memory for memory/mixed tests.
            if request.workload in ("memory_intensive", "mixed"):
                memory_data = bytearray(16 * 1024 * 1024)

                for offset in range(0, len(memory_data), 4096):
                    memory_data[offset] = 1

                del memory_data

        duration = time.perf_counter() - started

        job = {
            "job_id": job_id,
            "workload": request.workload,
            "iterations": request.iterations,
            "status": "completed",
            "duration_seconds": round(duration, 4),
            "result_checksum": checksum,
            "peak_process_memory_mb": round(
                peak_memory["value"], 2
            ),
            "completed_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        jobs[job_id] = job
        record_prometheus_job(request.workload, "completed", duration)
        return job

    except Exception as exc:
        record_prometheus_job(
            request.workload, "failed", time.perf_counter() - started
        )
        raise HTTPException(
            status_code=500,
            detail=f"Job processing failed: {type(exc).__name__}",
        ) from exc

    finally:
        stop_event.set()

        if sampler.is_alive():
            sampler.join(timeout=1)


@app.get("/jobs")
def list_jobs():
    return {"count": len(jobs), "jobs": list(jobs.values())}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]
