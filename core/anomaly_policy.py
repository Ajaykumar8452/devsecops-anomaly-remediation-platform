"""Central detection policies. Non-CPU defaults are observation-only."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class DetectionPolicy:
    signal: str
    target_id: str
    label: str
    mode: str
    trigger_threshold: float | None
    recovery_threshold: float | None
    persistence_seconds: float
    recovery_seconds: float
    cooldown_seconds: float
    sample_window_seconds: float
    min_samples: int
    max_sample_age_seconds: float
    comparison: str = "high"
    message: str = ""
    trigger_inclusive: bool = True
    recovery_inclusive: bool = True

    def __post_init__(self):
        if self.mode not in {"disabled", "observation", "enabled"}:
            raise ValueError(f"Invalid anomaly mode for {self.signal}: {self.mode}")
        if self.persistence_seconds < 0 or self.recovery_seconds < 0 or self.cooldown_seconds < 0:
            raise ValueError(f"Policy durations cannot be negative for {self.signal}")
        if self.sample_window_seconds <= 0 or self.max_sample_age_seconds <= 0:
            raise ValueError(f"Sample timing must be positive for {self.signal}")
        if self.min_samples < 1:
            raise ValueError(f"minimum sample count must be positive for {self.signal}")

    @property
    def enabled(self):
        return self.mode != "disabled" and self.trigger_threshold is not None


def _float(name, default):
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _int(name, default):
    return int(_float(name, default))


def _mode(name, default):
    value = os.getenv(name, default).strip().lower()
    if value not in {"disabled", "observation", "enabled"}:
        raise ValueError(f"{name} must be disabled, observation, or enabled")
    return value


POLICIES = {
    "backend_cpu_percent": DetectionPolicy(
        signal="backend_cpu_percent",
        target_id="fastapi_process",
        label="Backend Process CPU",
        mode=_mode("ANOMALY_CPU_MODE", "enabled"),
        trigger_threshold=_float("ANOMALY_CPU_TRIGGER_PERCENT", 80.0),
        recovery_threshold=_float("ANOMALY_CPU_RECOVERY_PERCENT", 70.0),
        persistence_seconds=_float("ANOMALY_CPU_PERSISTENCE_SECONDS", 60),
        recovery_seconds=_float("ANOMALY_CPU_RECOVERY_SECONDS", 30),
        cooldown_seconds=_float("ANOMALY_CPU_COOLDOWN_SECONDS", 0),
        sample_window_seconds=1,
        min_samples=1,
        max_sample_age_seconds=_float("ANOMALY_CPU_MAX_SAMPLE_AGE_SECONDS", 5),
        message="Backend process CPU exceeded its persistent anomaly policy.",
        recovery_inclusive=False,
    ),
    "backend_process_memory_mb": DetectionPolicy(
        signal="backend_process_memory_mb",
        target_id="fastapi_process",
        label="Memory (Backend Process RSS)",
        mode=_mode("ANOMALY_PROCESS_RSS_MODE", "observation"),
        trigger_threshold=_float("ANOMALY_PROCESS_RSS_TRIGGER_MB", 80.0),
        recovery_threshold=_float("ANOMALY_PROCESS_RSS_RECOVERY_MB", 72.0),
        persistence_seconds=_float("ANOMALY_PROCESS_RSS_PERSISTENCE_SECONDS", 30),
        recovery_seconds=_float("ANOMALY_PROCESS_RSS_RECOVERY_SECONDS", 30),
        cooldown_seconds=_float("ANOMALY_PROCESS_RSS_COOLDOWN_SECONDS", 300),
        sample_window_seconds=1,
        min_samples=1,
        max_sample_age_seconds=_float("ANOMALY_PROCESS_RSS_MAX_SAMPLE_AGE_SECONDS", 5),
        message="Backend process RSS exceeded its observation policy.",
    ),
    "system_memory_percent": DetectionPolicy(
        signal="system_memory_percent",
        target_id="host_system",
        label="Memory (System Utilization)",
        mode=_mode("ANOMALY_SYSTEM_MEMORY_MODE", "observation"),
        trigger_threshold=_float("ANOMALY_SYSTEM_MEMORY_TRIGGER_PERCENT", 90.0),
        recovery_threshold=_float("ANOMALY_SYSTEM_MEMORY_RECOVERY_PERCENT", 85.0),
        persistence_seconds=_float("ANOMALY_SYSTEM_MEMORY_PERSISTENCE_SECONDS", 30),
        recovery_seconds=_float("ANOMALY_SYSTEM_MEMORY_RECOVERY_SECONDS", 30),
        cooldown_seconds=_float("ANOMALY_SYSTEM_MEMORY_COOLDOWN_SECONDS", 300),
        sample_window_seconds=1,
        min_samples=1,
        max_sample_age_seconds=_float("ANOMALY_SYSTEM_MEMORY_MAX_SAMPLE_AGE_SECONDS", 5),
        message="Host system memory utilization exceeded its observation policy.",
    ),
    "application_health": DetectionPolicy(
        signal="application_health",
        target_id="fastapi_application",
        label="Application Health",
        mode=_mode("ANOMALY_HEALTH_MODE", "observation"),
        trigger_threshold=1,
        recovery_threshold=0,
        persistence_seconds=_float("ANOMALY_HEALTH_PERSISTENCE_SECONDS", 10),
        recovery_seconds=_float("ANOMALY_HEALTH_RECOVERY_SECONDS", 15),
        cooldown_seconds=_float("ANOMALY_HEALTH_COOLDOWN_SECONDS", 60),
        sample_window_seconds=_float("ANOMALY_HEALTH_WINDOW_SECONDS", 5),
        min_samples=1,
        max_sample_age_seconds=_float("ANOMALY_HEALTH_MAX_SAMPLE_AGE_SECONDS", 15),
        comparison="boolean_bad",
        message="Application internal health checks remained unhealthy.",
    ),
    "http_5xx_error_rate_percent": DetectionPolicy(
        signal="http_5xx_error_rate_percent",
        target_id="fastapi_http_service",
        label="HTTP 5xx Error Rate",
        mode=_mode("ANOMALY_HTTP_5XX_MODE", "observation"),
        trigger_threshold=_float("ANOMALY_HTTP_5XX_TRIGGER_PERCENT", 10.0),
        recovery_threshold=_float("ANOMALY_HTTP_5XX_RECOVERY_PERCENT", 5.0),
        persistence_seconds=_float("ANOMALY_HTTP_5XX_PERSISTENCE_SECONDS", 30),
        recovery_seconds=_float("ANOMALY_HTTP_5XX_RECOVERY_SECONDS", 30),
        cooldown_seconds=_float("ANOMALY_HTTP_5XX_COOLDOWN_SECONDS", 300),
        sample_window_seconds=_float("ANOMALY_HTTP_5XX_WINDOW_SECONDS", 60),
        min_samples=_int("ANOMALY_HTTP_5XX_MIN_SAMPLES", 5),
        max_sample_age_seconds=_float("ANOMALY_HTTP_5XX_MAX_SAMPLE_AGE_SECONDS", 65),
        message="HTTP 5xx rate exceeded its observation policy.",
    ),
    "average_latency_ms": DetectionPolicy(
        signal="average_latency_ms",
        target_id="fastapi_http_service",
        label="HTTP Response Latency",
        mode=_mode("ANOMALY_HTTP_LATENCY_MODE", "observation"),
        trigger_threshold=_float("ANOMALY_HTTP_LATENCY_TRIGGER_MS", 500.0),
        recovery_threshold=_float("ANOMALY_HTTP_LATENCY_RECOVERY_MS", 400.0),
        persistence_seconds=_float("ANOMALY_HTTP_LATENCY_PERSISTENCE_SECONDS", 30),
        recovery_seconds=_float("ANOMALY_HTTP_LATENCY_RECOVERY_SECONDS", 30),
        cooldown_seconds=_float("ANOMALY_HTTP_LATENCY_COOLDOWN_SECONDS", 300),
        sample_window_seconds=_float("ANOMALY_HTTP_LATENCY_WINDOW_SECONDS", 60),
        min_samples=_int("ANOMALY_HTTP_LATENCY_MIN_SAMPLES", 5),
        max_sample_age_seconds=_float("ANOMALY_HTTP_LATENCY_MAX_SAMPLE_AGE_SECONDS", 65),
        message="HTTP average response latency exceeded its observation policy.",
    ),
}


def condition_for(policy, value):
    """Return (triggered, recovered) using the configured hysteresis."""
    if value is None or policy.trigger_threshold is None:
        return False, False
    if policy.comparison == "boolean_bad":
        unhealthy = not bool(value)
        return unhealthy, not unhealthy
    recovery = policy.recovery_threshold
    if policy.comparison == "low":
        triggered = value <= policy.trigger_threshold if policy.trigger_inclusive else value < policy.trigger_threshold
        recovered = (
            value >= recovery if policy.recovery_inclusive else value > recovery
        ) if recovery is not None else False
        return triggered, recovered
    triggered = value >= policy.trigger_threshold if policy.trigger_inclusive else value > policy.trigger_threshold
    recovered = (
        value <= recovery if policy.recovery_inclusive else value < recovery
    ) if recovery is not None else False
    return triggered, recovered


def public_policy(policy):
    return {
        "signal": policy.signal,
        "target_id": policy.target_id,
        "label": policy.label,
        "mode": policy.mode,
        "enabled": policy.enabled,
        "trigger_threshold": policy.trigger_threshold,
        "recovery_threshold": policy.recovery_threshold,
        "persistence_seconds": policy.persistence_seconds,
        "recovery_seconds": policy.recovery_seconds,
        "cooldown_seconds": policy.cooldown_seconds,
        "sample_window_seconds": policy.sample_window_seconds,
        "minimum_samples": policy.min_samples,
        "max_sample_age_seconds": policy.max_sample_age_seconds,
    }
