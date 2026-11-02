"""Streamlit render and navigation coverage using a local standard-library API."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = PROJECT_ROOT / "application" / "dashboard.py"
PAGES = (
    "Overview",
    "Infrastructure Monitoring",
    "Anomaly Detection",
    "Job Management",
    "Remediation Center",
    "Audit History",
    "Grafana Integration",
)


def sample_signal(signal, target, value, trigger, recovery, status="ok"):
    return {
        "signal": signal,
        "target_id": target,
        "label": signal.replace("_", " ").title(),
        "state": "NORMAL",
        "metric_status": status,
        "policy_mode": "observation",
        "policy": {
            "mode": "observation",
            "trigger_threshold": trigger,
            "recovery_threshold": recovery,
            "persistence_seconds": 30,
            "recovery_seconds": 30,
            "cooldown_seconds": 300,
        },
        "current_value": value,
        "metric_timestamp": "2026-10-31T12:05:00+00:00",
        "pending_since": None,
        "recovery_since": None,
        "persistence_elapsed_seconds": 0,
        "recovery_elapsed_seconds": 0,
        "active_alert_id": None,
        "active_alert": None,
        "unknown_reason": "sample stale" if status != "ok" else None,
    }


class DashboardApiHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _respond(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in self.server.fail_paths:
            self._respond(503, {"detail": "simulated API outage"})
            return
        if path == "/health":
            payload = {"status": "healthy"}
        elif path == "/livez":
            payload = {"status": "alive"}
        elif path == "/readyz":
            payload = {
                "status": "ready",
                "ready": True,
                "checked_at": "2026-10-31T12:00:00+00:00",
                "components": {
                    "database": True,
                    "metrics_collector": True,
                    "anomaly_evaluator": True,
                    "health_watchdog": True,
                    "readiness_monitor": True,
                },
            }
        elif path == "/jobs":
            payload = {"count": len(self.server.jobs), "jobs": self.server.jobs}
        elif path == "/metrics/system":
            payload = {
                "process_cpu_percent": 10,
                "process_memory_mb": 60,
                "system_cpu_percent": 20,
                "system_memory_percent": 40,
            }
        elif path == "/metrics/history":
            payload = {
                "count": 1,
                "samples": [{
                    "timestamp": "2026-10-31T12:00:00+00:00",
                    "process_cpu_percent": 10,
                    "process_memory_mb": 60,
                    "system_cpu_percent": 20,
                    "system_memory_percent": 40,
                }],
            }
        elif path == "/metrics/http":
            payload = {
                "total_requests": 5,
                "status_codes": {"200": 4, "500": 1},
                "endpoint_counts": {"/health": 4, "/jobs": 1},
                "average_latency_ms": 20,
                "in_flight_requests": 0,
                "recent_requests": [{
                    "timestamp": "2026-10-31T12:00:00+00:00",
                    "method": "GET",
                    "endpoint": "/health",
                    "status_code": 200,
                    "latency_ms": 20,
                }],
            }
        elif path == "/anomalies/state":
            payload = self.server.anomaly_state
        elif path == "/anomalies/history":
            payload = {"count": len(self.server.alerts), "alerts": self.server.alerts}
        elif path == "/anomalies/active":
            active = [alert for alert in self.server.alerts if alert.get("status") == "confirmed"]
            payload = {"count": len(active), "alerts": active}
        elif path == "/anomalies/events":
            payload = {"count": len(self.server.events), "events": self.server.events}
        elif path == "/api/health":
            payload = {"database": "ok", "version": "test"}
        else:
            self._respond(404, {"detail": "not found"})
            return
        self._respond(200, payload)

    def do_POST(self):
        if urlparse(self.path).path != "/jobs":
            self._respond(404, {"detail": "not found"})
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        job = {
            "job_id": "job-test-1",
            "workload": body["workload"],
            "iterations": body["iterations"],
            "status": "completed",
            "duration_seconds": 0.25,
            "result_checksum": 123,
            "peak_process_memory_mb": 61,
            "completed_at": "2026-10-31T12:01:00+00:00",
        }
        self.server.jobs.append(job)
        self._respond(200, job)


def sample_alerts():
    return [
        {
            "alert_id": "cpu-alert-1234",
            "signal": "backend_cpu_percent",
            "status": "confirmed",
            "observed_value": 88.0,
            "threshold": 80.0,
            "started_at": "2026-10-31T12:00:00+00:00",
            "confirmed_at": "2026-10-31T12:01:00+00:00",
            "resolved_at": None,
        },
        {
            "alert_id": "http-alert-1234",
            "signal": "http_5xx_error_rate_percent",
            "status": "resolved",
            "observed_value": 20.0,
            "threshold": 10.0,
            "started_at": "2026-10-31T12:02:00+00:00",
            "confirmed_at": "2026-10-31T12:03:00+00:00",
            "resolved_at": "2026-10-31T12:04:00+00:00",
        },
    ]


def sample_state(alerts):
    signals = {
        "backend_cpu_percent": sample_signal("backend_cpu_percent", "fastapi_process", 10, 80, 70),
        "backend_process_memory_mb": sample_signal("backend_process_memory_mb", "fastapi_process", 60, 80, 72),
        "system_memory_percent": sample_signal("system_memory_percent", "host_system", 40, 90, 85),
        "application_health": sample_signal("application_health", "fastapi_application", True, 1, 0),
        "http_5xx_error_rate_percent": sample_signal("http_5xx_error_rate_percent", "fastapi_http_service", 0, 10, 5),
        "average_latency_ms": sample_signal("average_latency_ms", "fastapi_http_service", 20, 500, 400),
    }
    signals["system_memory_percent"].update({
        "metric_status": "unknown",
        "current_value": None,
        "unknown_reason": "sample stale",
    })
    return {
        "status": "normal",
        "thresholds": {
            "trigger_percent": 80,
            "recovery_percent": 70,
            "persistence_seconds": 60,
            "recovery_seconds": 30,
        },
        "pending_since": None,
        "recovery_since": None,
        "active_alert_id": None,
        "checked_at": "2026-10-31T12:05:00+00:00",
        "alert_history": alerts,
        "signals": signals,
    }


class DashboardRenderTests(unittest.TestCase):
    def setUp(self):
        self.alerts = sample_alerts()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardApiHandler)
        self.server.jobs = []
        self.server.alerts = self.alerts
        self.server.events = [{
            "event_id": 1,
            "alert_id": "cpu-alert-1234",
            "signal": "backend_cpu_percent",
            "target_id": "fastapi_process",
            "event_type": "confirmed",
            "occurred_at": "2026-10-31T12:01:00+00:00",
            "observed_value": 88.0,
            "details_json": "{}",
        }]
        self.server.anomaly_state = sample_state(self.alerts)
        self.server.fail_paths = set()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.old_env = {
            key: os.environ.get(key)
            for key in ("ANOMALY_DASHBOARD_API_URL", "GRAFANA_BASE_URL", "GRAFANA_DASHBOARD_URL")
        }
        os.environ["ANOMALY_DASHBOARD_API_URL"] = f"http://127.0.0.1:{self.server.server_port}"
        os.environ.pop("GRAFANA_BASE_URL", None)
        os.environ.pop("GRAFANA_DASHBOARD_URL", None)
        self.old_tempdir = tempfile.tempdir
        tempfile.tempdir = str(PROJECT_ROOT)

    def tearDown(self):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        tempfile.tempdir = self.old_tempdir
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def render_page(self, page="Overview"):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(DASHBOARD_PATH)).run(timeout=30)
        if page != "Overview":
            app.radio[0].set_value(page).run(timeout=30)
        self.assertEqual(len(app.exception), 0, f"Streamlit exception on {page}: {app.exception}")
        return app

    @staticmethod
    def rendered_text(app):
        names = ("title", "header", "subheader", "markdown", "caption", "info", "success", "warning", "error")
        values = []
        for name in names:
            for item in getattr(app, name, []):
                values.append(str(getattr(item, "value", item)))
        return "\n".join(values)

    def test_navigation_and_every_page_render(self):
        app = self.render_page()
        self.assertEqual(tuple(app.radio[0].options), PAGES)
        expected_headings = {
            "Overview": "Overview",
            "Infrastructure Monitoring": "Infrastructure monitoring",
            "Anomaly Detection": "Anomaly detection",
            "Job Management": "Job management",
            "Remediation Center": "Remediation center",
            "Audit History": "Audit history",
            "Grafana Integration": "Grafana integration",
        }
        for page in PAGES:
            with self.subTest(page=page):
                rendered = self.render_page(page)
                self.assertEqual(len(rendered.exception), 0)
                self.assertIn(expected_headings[page], self.rendered_text(rendered))
                if page == "Remediation Center":
                    self.assertTrue(any("Remediation is not implemented" in str(item.value) for item in rendered.info))

    def test_anomaly_page_covers_all_signals_unknown_and_alert_lifecycle_ist(self):
        app = self.render_page("Anomaly Detection")
        rendered = self.rendered_text(app)
        for signal in (
            "Backend Cpu Percent",
            "Backend Process Memory Mb",
            "System Memory Percent",
            "Application Health",
            "Http 5Xx Error Rate Percent",
            "Average Latency Ms",
        ):
            self.assertIn(signal, rendered)
        self.assertTrue(any("Metric state: UNKNOWN" in str(item.value) for item in app.info))
        alert_tables = [item.value for item in app.dataframe if "display_status" in item.value.columns]
        self.assertTrue(alert_tables)
        history = alert_tables[-1]
        self.assertIn("CONFIRMED", history["display_status"].iloc[0])
        self.assertIn("RESOLVED", history["display_status"].iloc[1])
        self.assertTrue(history["started_at"].str.endswith("IST").all())
        self.assertTrue(history["confirmed_at"].str.endswith("IST").all())
        active_table = alert_tables[0]
        self.assertEqual(active_table["display_status"].tolist(), ["CONFIRMED"])

    def test_audit_page_shows_lifecycle_events_with_ist_timestamps(self):
        app = self.render_page("Audit History")
        event_tables = [item.value for item in app.dataframe if "event_type" in item.value.columns]
        self.assertTrue(event_tables)
        self.assertEqual(event_tables[0]["event_type"].iloc[0], "confirmed")
        self.assertTrue(event_tables[0]["occurred_at"].str.endswith("IST").all())
        self.assertTrue(any("Remediation audit" in str(item.value) for item in app.subheader))

    def test_job_submission_and_job_history(self):
        app = self.render_page("Job Management")
        app.selectbox[0].set_value("normal")
        submit = next(button for button in app.button if button.label == "Run processing job")
        submit.click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(self.server.jobs), 1)
        self.assertEqual(self.server.jobs[0]["workload"], "normal")
        job_tables = [item.value for item in app.dataframe if "job_id" in item.value.columns]
        self.assertTrue(job_tables)
        self.assertEqual(job_tables[0]["job_id"].iloc[0], "job-test-1")

    def test_api_failures_render_unavailable_state(self):
        self.server.fail_paths.add("/metrics/system")
        app = self.render_page("Overview")
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("Resource metrics are unavailable" in str(item.value) for item in app.warning))

        self.server.fail_paths.add("/anomalies/state")
        app = self.render_page("Anomaly Detection")
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("Anomaly data is unavailable" in str(item.value) for item in app.warning))

    def test_grafana_is_optional_and_configurable(self):
        app = self.render_page("Grafana Integration")
        self.assertTrue(any("not configured" in str(item.value).lower() for item in app.info))
        os.environ["GRAFANA_BASE_URL"] = f"http://127.0.0.1:{self.server.server_port}"
        os.environ["GRAFANA_DASHBOARD_URL"] = "http://127.0.0.1:3000/d/test"
        app = self.render_page("Grafana Integration")
        self.assertTrue(any("Grafana is reachable" in str(item.value) for item in app.success))
        self.assertEqual(len(app.link_button), 1)
        os.environ["GRAFANA_BASE_URL"] = "http://127.0.0.1:1"
        os.environ.pop("GRAFANA_DASHBOARD_URL", None)
        app = self.render_page("Grafana Integration")
        self.assertTrue(any("currently unavailable" in str(item.value) for item in app.warning))

    def test_three_second_auto_refresh_remains_configured(self):
        for relative_path in (
            "application/dashboard_pages/anomalies.py",
            "application/dashboard_pages/infrastructure.py",
        ):
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn('@st.fragment(run_every="3s")', source)


if __name__ == "__main__":
    unittest.main()
