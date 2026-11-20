"""Tests for Prometheus instrumentation reusing existing application paths."""

import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

_test_directory = tempfile.TemporaryDirectory(prefix="prometheus-metrics-tests-")
os.environ.setdefault(
    "ALERT_DATABASE_PATH",
    str(Path(_test_directory.name) / "alerts.db"),
)

import main
from core import prometheus_metrics as metrics


def metric_value(name, labels=None):
    labels = labels or {}
    for family in metrics.REGISTRY.collect():
        for sample in family.samples:
            if sample.name == name and all(
                sample.labels.get(key) == value for key, value in labels.items()
            ):
                return sample.value
    raise AssertionError(f"Metric sample not found: {name} {labels}")


class PrometheusEndpointTests(unittest.TestCase):
    def test_metrics_endpoint_has_prometheus_content_type_and_expected_names(self):
        response = main.prometheus_metrics()
        body = response.body.decode("utf-8")
        self.assertIn("text/plain", response.media_type)
        for name in (
            "platform_backend_process_cpu_percent",
            "platform_backend_process_resident_memory_bytes",
            "platform_system_cpu_percent",
            "platform_system_memory_utilization_percent",
            "platform_http_requests_total",
            "platform_http_request_duration_seconds",
            "platform_http_requests_in_flight",
            "platform_http_5xx_error_rate_percent",
            "platform_http_response_latency_ms",
            "platform_anomaly_state",
            "platform_jobs_total",
            "platform_job_duration_seconds",
        ):
            self.assertIn(name, body)

    def test_existing_json_metrics_contracts_are_unchanged(self):
        http = main.get_http_metrics()
        self.assertEqual(
            set(http),
            {
                "total_requests", "status_codes", "endpoint_counts",
                "average_latency_ms", "in_flight_requests", "recent_requests",
            },
        )
        history = main.get_metrics_history()
        self.assertEqual(set(history), {"count", "samples"})
        system = main.system_metrics()
        self.assertEqual(
            set(system),
            {
                "process_cpu_percent", "process_memory_mb",
                "system_cpu_percent", "system_memory_percent",
            },
        )

    def test_registry_is_single_dedicated_registry(self):
        names = [family.name for family in metrics.REGISTRY.collect()]
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn("process", names)
        self.assertNotIn("python_gc_objects_collected", names)


class PrometheusMiddlewareTests(unittest.TestCase):
    def request(self, path, method="GET", route="/jobs/{job_id}"):
        return SimpleNamespace(
            url=SimpleNamespace(path=path),
            method=method,
            scope={"route": SimpleNamespace(path=route)},
        )

    def call_middleware(self, request, status=200):
        async def call_next(_request):
            return SimpleNamespace(status_code=status)

        coroutine = main.collect_http_metrics(request, call_next)
        try:
            coroutine.send(None)
        except StopIteration as completed:
            return completed.value
        self.fail("Test call_next unexpectedly suspended the middleware coroutine")

    def test_http_requests_use_bounded_method_and_route_template_labels(self):
        before = metric_value(
            "platform_http_requests_total",
            {"method": "OTHER", "route": "/jobs/{job_id}", "status_class": "2xx"},
        ) if any(
            sample.name == "platform_http_requests_total"
            and sample.labels == {
                "method": "OTHER", "route": "/jobs/{job_id}", "status_class": "2xx"
            }
            for family in metrics.REGISTRY.collect() for sample in family.samples
        ) else 0
        self.call_middleware(self.request("/jobs/secret-user-id", "BREW"), 201)
        after = metric_value(
            "platform_http_requests_total",
            {"method": "OTHER", "route": "/jobs/{job_id}", "status_class": "2xx"},
        )
        self.assertEqual(after - before, 1)
        self.assertGreaterEqual(
            metric_value(
                "platform_http_request_duration_seconds_count",
                {"method": "OTHER", "route": "/jobs/{job_id}"},
            ),
            1,
        )
        self.assertNotIn("/jobs/secret-user-id", str(metrics.REGISTRY.collect()))
        self.call_middleware(self.request("/health", "POST", "/health"), 503)
        self.assertGreaterEqual(
            metric_value(
                "platform_http_requests_total",
                {"method": "POST", "route": "/health", "status_class": "5xx"},
            ),
            1,
        )

    def test_metrics_scrapes_do_not_increment_business_metrics(self):
        with main.http_metrics_lock:
            before_http_total = main.http_metrics["total_requests"]
            before_recent_count = len(main.http_metrics["recent_requests"])
        before_counter = sum(
            sample.value
            for family in metrics.REGISTRY.collect()
            for sample in family.samples
            if sample.name == "platform_http_requests_total"
        )
        self.call_middleware(self.request("/metrics"))
        with main.http_metrics_lock:
            self.assertEqual(main.http_metrics["total_requests"], before_http_total)
            self.assertEqual(len(main.http_metrics["recent_requests"]), before_recent_count)
        after_counter = sum(
            sample.value
            for family in metrics.REGISTRY.collect()
            for sample in family.samples
            if sample.name == "platform_http_requests_total"
        )
        self.assertEqual(after_counter, before_counter)


class ExistingDataPathMetricTests(unittest.TestCase):
    def test_collector_updates_process_and_system_gauges_from_existing_sample(self):
        sample = {
            "process_cpu_percent": 12.5,
            "process_memory_mb": 10.0,
            "system_cpu_percent": 20.5,
            "system_memory_percent": 62.0,
        }
        metrics.update_collector_gauges(sample, process_rss_bytes=10_123_456)
        self.assertEqual(metric_value("platform_backend_process_cpu_percent"), 12.5)
        self.assertEqual(
            metric_value("platform_backend_process_resident_memory_bytes"),
            10_123_456,
        )
        self.assertEqual(metric_value("platform_system_cpu_percent"), 20.5)
        self.assertEqual(
            metric_value("platform_system_memory_utilization_percent"), 62.0
        )

    def test_anomaly_state_mapping_is_bounded_and_readable(self):
        metrics.update_anomaly_state({
            "signal": "backend_cpu_percent", "target_id": "fastapi_process",
            "status": "RECOVERING", "metric_status": "ok",
        })
        self.assertEqual(
            metric_value(
                "platform_anomaly_state",
                {"signal": "backend_cpu_percent", "target": "fastapi_process", "state": "RECOVERING"},
            ),
            metrics.ANOMALY_STATE_CODES["RECOVERING"],
        )
        metrics.update_anomaly_state({
            "signal": "backend_cpu_percent", "target_id": "fastapi_process",
            "status": "CONFIRMED", "metric_status": "unknown",
        })
        self.assertEqual(
            metric_value(
                "platform_anomaly_state",
                {"signal": "backend_cpu_percent", "target": "fastapi_process", "state": "UNKNOWN"},
            ),
            metrics.ANOMALY_STATE_CODES["UNKNOWN"],
        )
        metrics.update_anomaly_state({
            "signal": "user_supplied_label", "target_id": "arbitrary",
            "status": "CONFIRMED", "metric_status": "ok",
        })
        self.assertEqual(len(metrics.ANOMALY_IDENTITIES), 6)

    def test_http_anomaly_gauges_reuse_evaluator_observations(self):
        observations = [
            ("http_5xx_error_rate_percent", 12.0, None, None),
            ("average_latency_ms", 640.0, None, None),
        ]
        metrics.update_http_anomaly_gauges(observations)
        self.assertEqual(metric_value("platform_http_5xx_error_rate_percent"), 12.0)
        self.assertEqual(metric_value("platform_http_response_latency_ms"), 640.0)

    def test_job_metrics_use_only_bounded_labels_and_no_job_id(self):
        before = metric_value(
            "platform_jobs_total",
            {"workload": "normal", "status": "completed"},
        ) if any(
            sample.name == "platform_jobs_total"
            and sample.labels == {"workload": "normal", "status": "completed"}
            for family in metrics.REGISTRY.collect() for sample in family.samples
        ) else 0
        metrics.record_job("normal", "completed", 0.25)
        after = metric_value(
            "platform_jobs_total",
            {"workload": "normal", "status": "completed"},
        )
        self.assertEqual(after - before, 1)
        self.assertGreaterEqual(
            metric_value(
                "platform_job_duration_seconds_count", {"workload": "normal"}
            ),
            1,
        )
        self.assertNotIn("job_id", str(metrics.REGISTRY.collect()))

    def test_successful_job_endpoint_records_bounded_workload_metrics(self):
        before = sum(
            sample.value
            for family in metrics.REGISTRY.collect()
            for sample in family.samples
            if sample.name == "platform_jobs_total"
            and sample.labels == {"workload": "normal", "status": "completed"}
        )
        job = main.create_job(main.JobRequest(workload="normal", iterations=1))
        self.assertEqual(job["status"], "completed")
        after = metric_value(
            "platform_jobs_total",
            {"workload": "normal", "status": "completed"},
        )
        self.assertEqual(after - before, 1)


if __name__ == "__main__":
    unittest.main()
