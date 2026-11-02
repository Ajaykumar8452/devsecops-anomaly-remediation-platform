"""Temporary-database coverage for persistent CPU alert storage."""

import os
import tempfile
import unittest
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
_test_directory = tempfile.TemporaryDirectory(prefix="alert-storage-tests-", dir=_project_root)
os.environ["ALERT_DATABASE_PATH"] = str(Path(_test_directory.name) / "nested" / "alerts.db")

from core import database
database.initialize_database()

import main


class AlertStorageTests(unittest.TestCase):
    def setUp(self):
        with database._transaction() as connection:
            connection.execute("DELETE FROM alerts")
            connection.execute("DELETE FROM anomaly_states")
            connection.execute("DELETE FROM alert_events")

    def alert(self, alert_id="test-alert-1"):
        return {
            "alert_id": alert_id,
            "signal": "backend_cpu_percent",
            "status": "confirmed",
            "observed_value": 91.25,
            "threshold": 80.0,
            "started_at": "2026-10-31T10:00:00+00:00",
            "confirmed_at": "2026-10-31T10:01:00+00:00",
            "resolved_at": None,
            "message": "CPU persistence test alert",
        }

    def test_initialization_and_schema(self):
        self.assertTrue(database.DATABASE_PATH.exists())
        with database._transaction() as connection:
            names = {row["name"] for row in connection.execute("PRAGMA table_info(alerts)")}
        self.assertTrue({"alert_id", "status", "created_at", "updated_at"}.issubset(names))

    def test_create_then_resolve_updates_single_record(self):
        alert = self.alert()
        database.save_alert(alert)
        self.assertEqual(database.get_alert_by_id(alert["alert_id"])["status"], "confirmed")
        self.assertTrue(database.resolve_alert(alert["alert_id"], "2026-10-31T10:02:00+00:00"))
        self.assertFalse(database.resolve_alert(alert["alert_id"], "2026-10-31T10:03:00+00:00"))
        stored = database.get_alert_by_id(alert["alert_id"])
        self.assertEqual(stored["status"], "resolved")
        self.assertEqual(stored["resolved_at"], "2026-10-31T10:02:00+00:00")
        self.assertEqual(len(database.get_all_alerts()), 1)

    def test_history_active_and_api_retrieval(self):
        database.save_alert(self.alert())
        database.save_alert(self.alert("test-alert-2"))
        history = main.get_cpu_anomaly_history(limit=1)
        active = main.get_active_cpu_anomalies()
        state = main.get_cpu_anomaly_state()
        self.assertEqual(history["count"], 1)
        self.assertEqual(active["count"], 2)
        self.assertEqual(len(state["alert_history"]), 2)

    def test_anomaly_state_adds_signals_without_removing_legacy_cpu_fields(self):
        state = main.get_cpu_anomaly_state()
        self.assertTrue({
            "status", "thresholds", "pending_since", "recovery_since",
            "active_alert_id", "alert_history", "signals",
        }.issubset(state))
        self.assertEqual(state["thresholds"]["trigger_percent"], 80.0)
        self.assertEqual(state["thresholds"]["recovery_percent"], 70.0)
        self.assertEqual(state["thresholds"]["persistence_seconds"], 60)
        self.assertEqual(state["thresholds"]["recovery_seconds"], 30)
        self.assertEqual(len(state["signals"]), 6)
        self.assertIn("backend_process_memory_mb", state["signals"])
        self.assertIn("system_memory_percent", state["signals"])
        self.assertIn("application_health", state["signals"])
        self.assertIn("http_5xx_error_rate_percent", state["signals"])
        self.assertIn("average_latency_ms", state["signals"])
        self.assertIn("backend_cpu_percent", state["signals"])

    def test_restart_does_not_restore_resolved_alert_as_active(self):
        alert = self.alert()
        database.save_alert(alert)
        database.resolve_alert(alert["alert_id"], "2026-10-31T10:02:00+00:00")
        # Startup reconciliation must not restore a resolved record as active.
        main.restore_active_alert_state()
        self.assertNotEqual(main.cpu_anomaly_state["status"], "confirmed")
        self.assertIsNone(main.cpu_anomaly_state["active_alert_id"])
        self.assertEqual(database.get_all_alerts()[0]["status"], "resolved")

    def test_dashboard_fetches_persisted_history_and_formats_ist(self):
        app_directory = Path(__file__).resolve().parents[1] / "application"
        api_source = (app_directory / "dashboard_api.py").read_text(encoding="utf-8")
        ui_source = (app_directory / "dashboard_ui.py").read_text(encoding="utf-8")
        self.assertIn("/anomalies/history", api_source)
        self.assertIn('tz_convert("Asia/Kolkata")', ui_source)
        self.assertIn("View complete alert IDs and details", ui_source)


if __name__ == "__main__":
    unittest.main()
