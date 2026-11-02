"""Small, failure-tolerant client for the existing FastAPI endpoints."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import requests


DEFAULT_TIMEOUT = 5


def api_base_url():
    return os.getenv("ANOMALY_DASHBOARD_API_URL", "http://127.0.0.1:8000").rstrip("/")


def grafana_settings():
    return (
        os.getenv("GRAFANA_BASE_URL", "").strip().rstrip("/"),
        os.getenv("GRAFANA_DASHBOARD_URL", "").strip(),
    )


def grafana_internal_url():
    """Return Grafana's Docker-network URL for server-side health checks."""
    return os.getenv("GRAFANA_INTERNAL_URL", "").strip().rstrip("/")


def request_json(path: str, *, params=None, timeout=DEFAULT_TIMEOUT):
    """Return ``(status_code, payload, error)`` without raising on API failures."""
    try:
        response = requests.get(f"{api_base_url()}{path}", params=params, timeout=timeout)
    except requests.RequestException as exc:
        return None, None, str(exc)

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if not response.ok:
        detail = (payload or {}).get("detail") if isinstance(payload, dict) else None
        return response.status_code, payload, detail or f"HTTP {response.status_code}"
    return response.status_code, payload, None


def get_json(path: str, *, params=None, timeout=DEFAULT_TIMEOUT):
    status, payload, error = request_json(path, params=params, timeout=timeout)
    if status is None or status < 200 or status >= 300:
        return None
    return payload if isinstance(payload, dict) else None


def get_liveness():
    return request_json("/livez", timeout=3)


def get_readiness():
    # A 503 response carries useful component details, so retain its payload.
    return request_json("/readyz", timeout=3)


def get_system_metrics():
    return get_json("/metrics/system")


def get_metrics_history():
    return get_json("/metrics/history")


def get_http_metrics():
    return get_json("/metrics/http")


def get_anomaly_state():
    return get_json("/anomalies/state")


def get_anomaly_history(limit=500):
    payload = get_json("/anomalies/history", params={"limit": limit})
    return payload.get("alerts", []) if payload is not None else None


def get_active_alerts():
    payload = get_json("/anomalies/active")
    return payload.get("alerts", []) if payload is not None else None


def get_anomaly_events(limit=500):
    payload = get_json("/anomalies/events", params={"limit": limit})
    return payload.get("events", []) if payload is not None else None


def get_jobs():
    payload = get_json("/jobs")
    return payload.get("jobs", []) if payload is not None else None


def submit_job(workload: str, iterations: int):
    try:
        response = requests.post(
            f"{api_base_url()}/jobs",
            json={"workload": workload, "iterations": iterations},
            timeout=180,
        )
    except requests.RequestException as exc:
        return None, str(exc)

    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not response.ok:
        detail = (payload or {}).get("detail") if isinstance(payload, dict) else None
        return None, detail or f"HTTP {response.status_code}"
    return payload, None


def valid_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def check_grafana(base_url: str, *, health_url: str | None = None):
    """Return Grafana's availability without making it a dashboard dependency."""
    if not valid_http_url(base_url):
        return False, "Configure a valid HTTP or HTTPS Grafana URL."
    endpoint = (health_url or base_url).rstrip("/")
    if not valid_http_url(endpoint):
        return False, "Configure a valid HTTP or HTTPS Grafana health URL."
    try:
        response = requests.get(f"{endpoint}/api/health", timeout=2)
    except requests.RequestException as exc:
        return False, str(exc)
    if response.ok:
        return True, None
    return False, f"Grafana health endpoint returned HTTP {response.status_code}."
