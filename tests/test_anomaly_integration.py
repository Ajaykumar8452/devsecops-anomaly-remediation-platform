"""Integration checks for metric adapters and per-signal policy inputs."""

from collections import deque
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from core.anomaly_engine import initial_state

_project_root = Path(__file__).resolve().parents[1]
_test_db = tempfile.TemporaryDirectory(
    prefix="anomaly-adapter-tests-", dir=_project_root
)
os.environ.setdefault(
    "ALERT_DATABASE_PATH",
    str(Path(_test_db.name) / "alerts.db"),
)

import main


class MetricAdapterTests(unittest.TestCase):
    def test_livez_and_readyz_report_healthy_cached_status(self):
        now = datetime.now(timezone.utc)
        healthy = {
            "database": True,
            "metrics_collector": True,
            "anomaly_evaluator": True,
            "health_watchdog": True,
        }
        with patch.object(main, "readiness_snapshot", {
            "ready": True,
            "checked_at": now.isoformat(),
            "components": healthy,
        }):
            self.assertEqual(main.livez(), {"status": "alive"})
            response = main.readyz()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.body)["status"], "ready")

    def test_livez_stays_alive_when_database_is_unavailable_but_readyz_is_503(self):
        now = datetime.now(timezone.utc)
        latest = {"timestamp": now.isoformat()}
        with patch.object(main, "check_database", return_value=False) as database_check, \
                patch.object(main.metrics_thread, "is_alive", return_value=True), \
                patch.object(main, "metrics_history", deque([latest])), \
                patch.object(main, "cpu_evaluator_thread", Mock(is_alive=lambda: True)), \
                patch.object(main, "health_watchdog_thread", Mock(is_alive=lambda: True)), \
                patch.object(main, "evaluator_heartbeat_at", now), \
                patch.object(main, "health_watchdog_heartbeat_at", now), \
                patch.object(main, "readiness_snapshot", {}):
            snapshot = main._refresh_readiness_snapshot(now)
            self.assertFalse(snapshot["ready"])
            self.assertFalse(snapshot["components"]["database"])
            database_check.assert_called_once_with(timeout_seconds=1)
            self.assertEqual(main.livez(), {"status": "alive"})
            response = main.readyz()
            self.assertEqual(response.status_code, 503)
            self.assertEqual(json.loads(response.body)["status"], "not_ready")
            database_check.assert_called_with(timeout_seconds=1)

    def test_readyz_fails_for_stale_components_and_stale_cache(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(seconds=100)
        with patch.object(main, "check_database", return_value=True), \
                patch.object(main.metrics_thread, "is_alive", return_value=False), \
                patch.object(main, "metrics_history", deque()), \
                patch.object(main, "cpu_evaluator_thread", Mock(is_alive=lambda: True)), \
                patch.object(main, "health_watchdog_thread", Mock(is_alive=lambda: False)), \
                patch.object(main, "evaluator_heartbeat_at", old), \
                patch.object(main, "health_watchdog_heartbeat_at", old), \
                patch.object(main, "readiness_snapshot", {}):
            snapshot = main._refresh_readiness_snapshot(now)
            self.assertFalse(snapshot["ready"])
            self.assertFalse(snapshot["components"]["metrics_collector"])
            self.assertFalse(snapshot["components"]["anomaly_evaluator"])
            self.assertFalse(snapshot["components"]["health_watchdog"])

        stale_snapshot = {
            "ready": True,
            "checked_at": old.isoformat(),
            "components": {
                "database": True,
                "metrics_collector": True,
                "anomaly_evaluator": True,
                "health_watchdog": True,
            },
        }
        with patch.object(main, "readiness_snapshot", stale_snapshot):
            response = main._readiness_response(now)
            body = json.loads(response.body)
            self.assertEqual(response.status_code, 503)
            self.assertFalse(body["components"]["readiness_monitor"])

    def test_invalid_metric_values_are_classified_unknown(self):
        invalid_values = (None, "invalid", float("nan"), float("inf"), True)
        for signal in main.POLICIES:
            for value in invalid_values:
                with self.subTest(signal=signal, value=value):
                    reason = main._metric_value_invalid_reason(signal, value)
                    if signal == "application_health" and isinstance(value, bool):
                        self.assertIsNone(reason)
                    else:
                        self.assertIsNotNone(reason)

    def test_invalid_observation_enters_unknown_and_valid_sample_resumes(self):
        signal = "backend_process_memory_mb"
        policy = main.POLICIES[signal]
        key = (signal, policy.target_id)
        original = deepcopy(main.signal_states[key])
        now = datetime.now(timezone.utc)
        try:
            with main.anomaly_state_lock, patch.object(main, "persist_engine_updates"):
                main.signal_states[key] = initial_state(signal, policy.target_id)
                main._process_signal_samples(
                    [(signal, "corrupt-value", now, None)],
                    now=now,
                )
                unknown = main.signal_states[key]
                self.assertEqual(unknown["metric_status"], "unknown")
                self.assertEqual(unknown["unknown_reason"], "invalid numeric metric value")

                main._process_signal_samples(
                    [(signal, policy.trigger_threshold + 1, now + timedelta(seconds=1), None)],
                    now=now + timedelta(seconds=1),
                )
                resumed = main.signal_states[key]
                self.assertEqual(resumed["metric_status"], "ok")
                self.assertEqual(resumed["status"], "PENDING")

                stale_time = now - timedelta(seconds=policy.max_sample_age_seconds + 1)
                main._process_signal_samples(
                    [(signal, 20.0, stale_time, None)],
                    now=now + timedelta(seconds=2),
                )
                stale = main.signal_states[key]
                self.assertEqual(stale["metric_status"], "unknown")
                self.assertEqual(stale["status"], "PENDING")

                main._process_signal_samples(
                    [(signal, policy.trigger_threshold + 1, now + timedelta(seconds=3), None)],
                    now=now + timedelta(seconds=3),
                )
                self.assertEqual(main.signal_states[key]["metric_status"], "ok")
                self.assertEqual(main.signal_states[key]["status"], "PENDING")
        finally:
            with main.anomaly_state_lock:
                main.signal_states[key] = original

    def test_stale_sample_is_not_fresh_for_any_signal(self):
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        stale_time = now - timedelta(seconds=10_000)
        for policy in main.POLICIES.values():
            with self.subTest(signal=policy.signal):
                self.assertFalse(main._metric_value_is_fresh(stale_time, policy, now))

    def test_application_health_checks_internal_dependencies_and_heartbeat(self):
        now = datetime.now(timezone.utc)
        latest = {
            "timestamp": now.isoformat(),
            "process_cpu_percent": 1.0,
            "process_memory_mb": 60.0,
            "system_memory_percent": 40.0,
        }
        with patch.object(main, "check_database", return_value=True), \
                patch.object(main.metrics_thread, "is_alive", return_value=True), \
                patch.object(main, "cpu_evaluator_thread") as evaluator, \
                patch.object(main, "evaluator_heartbeat_at", now), \
                patch.object(main, "metrics_history", deque([latest])):
            evaluator.is_alive.return_value = True
            self.assertTrue(main._application_health_observation(now))
            self.assertTrue(all(main.health_components.values()))

            evaluator.is_alive.return_value = False
            self.assertFalse(main._application_health_observation(now))
            self.assertFalse(main.health_components["evaluator"])

            evaluator.is_alive.return_value = True
            with patch.object(
                main,
                "evaluator_heartbeat_at",
                now - timedelta(seconds=main.POLICIES["application_health"].max_sample_age_seconds + 1),
            ):
                self.assertFalse(main._application_health_observation(now))
                self.assertFalse(main.health_components["evaluator"])

        with patch.object(main, "check_database", return_value=False):
            self.assertFalse(main._application_health_observation(now))
            self.assertFalse(main.health_components["database"])

        with patch.object(main.metrics_thread, "is_alive", return_value=False):
            self.assertFalse(main._application_health_observation(now))
            self.assertFalse(main.health_components["metrics_collector"])

        stale = dict(latest)
        stale["timestamp"] = "2020-01-01T00:00:00+00:00"
        with patch.object(main, "metrics_history", deque([stale])):
            self.assertFalse(main._application_health_observation(now))
            self.assertFalse(main.health_components["metrics_fresh"])

    def test_http_adapter_calculates_rate_and_latency_from_separate_windows(self):
        now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        samples = []
        for index, status in enumerate((500, 500, 200, 200, 200)):
            samples.append({
                "timestamp": now.isoformat(),
                "method": "GET",
                "endpoint": "/api",
                "status_code": status,
                "latency_ms": 900.0 + index,
            })

        with main.http_metrics_lock:
            original = main.http_metrics["recent_requests"]
            main.http_metrics["recent_requests"] = deque(samples, maxlen=1000)
        try:
            observations = main._evaluate_http_metrics(now)
        finally:
            with main.http_metrics_lock:
                main.http_metrics["recent_requests"] = original

        by_signal = {signal: value for signal, value, _, _ in observations}
        self.assertEqual(by_signal["http_5xx_error_rate_percent"], 40.0)
        self.assertEqual(by_signal["average_latency_ms"], 902.0)

    def test_http_metrics_are_unknown_below_minimum_sample_count(self):
        now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        with main.http_metrics_lock:
            original = main.http_metrics["recent_requests"]
            main.http_metrics["recent_requests"] = deque([
                {
                    "timestamp": now.isoformat(),
                    "status_code": 500,
                    "latency_ms": 900,
                }
            ], maxlen=1000)
        try:
            observations = main._evaluate_http_metrics(now)
        finally:
            with main.http_metrics_lock:
                main.http_metrics["recent_requests"] = original

        self.assertTrue(all(value is None and timestamp is None for _, value, timestamp, _ in observations))

    def test_normal_http_traffic_is_below_both_anomaly_thresholds(self):
        now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        samples = [
            {
                "timestamp": now.isoformat(),
                "status_code": 200,
                "latency_ms": 100.0,
            }
            for _ in range(5)
        ]
        with main.http_metrics_lock:
            original = main.http_metrics["recent_requests"]
            main.http_metrics["recent_requests"] = deque(samples, maxlen=1000)
        try:
            observations = main._evaluate_http_metrics(now)
        finally:
            with main.http_metrics_lock:
                main.http_metrics["recent_requests"] = original
        by_signal = {signal: value for signal, value, _, _ in observations}
        self.assertEqual(by_signal["http_5xx_error_rate_percent"], 0.0)
        self.assertEqual(by_signal["average_latency_ms"], 100.0)

    def test_stale_http_samples_become_unknown(self):
        now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        stale_timestamp = (now - timedelta(seconds=120)).isoformat()
        samples = [
            {
                "timestamp": stale_timestamp,
                "status_code": 500,
                "latency_ms": 900.0,
            }
            for _ in range(5)
        ]
        with main.http_metrics_lock:
            original = main.http_metrics["recent_requests"]
            main.http_metrics["recent_requests"] = deque(samples, maxlen=1000)
        try:
            observations = main._evaluate_http_metrics(now)
        finally:
            with main.http_metrics_lock:
                main.http_metrics["recent_requests"] = original
        self.assertTrue(all(
            value is None and timestamp is None
            for _, value, timestamp, _ in observations
        ))


if __name__ == "__main__":
    unittest.main()
