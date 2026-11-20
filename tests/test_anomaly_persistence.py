"""SQLite migration, lifecycle, and restart integration tests."""

import importlib.util
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.anomaly_engine import advance_state, initial_state, restore_states
from core.anomaly_policy import POLICIES


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_MODULE_PATH = PROJECT_ROOT / "core" / "database.py"


def isolated_database_module():
    spec = importlib.util.spec_from_file_location(
        "isolated_alert_database", DATABASE_MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnomalyPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory(
            prefix="anomaly-persistence-"
        )
        self.database = isolated_database_module()
        self.database.DATABASE_PATH = Path(self.temp_directory.name) / "alerts.db"
        self.database.initialize_database()

    def tearDown(self):
        self.temp_directory.cleanup()

    def make_alert(self, signal, target_id, alert_id):
        return {
            "alert_id": alert_id,
            "signal": signal,
            "target_id": target_id,
            "status": "confirmed",
            "observed_value": 91.0,
            "threshold": 80.0,
            "recovery_threshold": 70.0,
            "started_at": "2026-10-31T12:00:00+00:00",
            "confirmed_at": "2026-10-31T12:00:10+00:00",
            "resolved_at": None,
            "message": "integration alert",
            "policy_mode": "observation",
        }

    def test_migration_preserves_legacy_alert_rows(self):
        legacy_path = Path(self.temp_directory.name) / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        connection.execute(
            """
            CREATE TABLE alerts (
                alert_id TEXT PRIMARY KEY, signal TEXT NOT NULL,
                status TEXT NOT NULL, observed_value REAL NOT NULL,
                threshold REAL NOT NULL, started_at TEXT NOT NULL,
                confirmed_at TEXT NOT NULL, resolved_at TEXT,
                message TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-id", "backend_cpu_percent", "resolved", 88.0,
                80.0, "start", "confirm", "resolve", "old alert", "created", "updated",
            ),
        )
        connection.commit()
        connection.close()

        self.database.DATABASE_PATH = legacy_path
        self.database.initialize_database()
        old = self.database.get_alert_by_id("legacy-id")
        self.assertEqual(old["status"], "resolved")
        self.assertEqual(old["target_id"], "fastapi_process")
        self.assertIn("anomaly_states", {
            row["name"] for row in self._table_rows()
        })
        self.assertIn("alert_events", {
            row["name"] for row in self._table_rows()
        })

    def _table_rows(self):
        with self.database._transaction() as connection:
            return connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()

    def test_transactional_lifecycle_and_event_history(self):
        signal = "backend_process_memory_mb"
        target = "fastapi_process"
        policy = replace(
            POLICIES[signal], persistence_seconds=10,
            recovery_seconds=5, cooldown_seconds=20,
        )
        start = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        state = initial_state(signal, target)
        state.update({
            "status": "PENDING",
            "pending_since": start.isoformat(),
            "last_processed_sample": start.isoformat(),
        })
        self.database.persist_engine_updates([{
            "state": state,
            "events": [{"event_type": "pending_started"}],
        }])

        state, events = advance_state(
            state,
            triggered=True,
            recovered=False,
            sample_time=start + timedelta(seconds=10),
            observed_value=91.0,
            policy=policy,
            alert_id_factory=lambda: "lifecycle-alert",
        )
        alert = next(event["alert"] for event in events if event["event_type"] == "confirmed")
        self.database.persist_engine_updates([{
            "state": state, "alert": alert, "events": events,
        }])
        self.assertEqual(self.database.get_alert_by_id("lifecycle-alert")["status"], "confirmed")

        state, events = advance_state(
            state,
            triggered=False,
            recovered=True,
            sample_time=start + timedelta(seconds=11),
            observed_value=60.0,
            policy=policy,
        )
        self.database.persist_engine_updates([{"state": state, "events": events}])
        state, events = advance_state(
            state,
            triggered=False,
            recovered=True,
            sample_time=start + timedelta(seconds=16),
            observed_value=60.0,
            policy=policy,
        )
        resolution = next(event for event in events if event["event_type"] == "resolved")
        self.database.persist_engine_updates([{
            "state": state,
            "resolve": {
                "alert_id": resolution["alert_id"],
                "resolved_at": resolution["resolved_at"],
            },
            "events": events,
        }])

        self.assertEqual(len(self.database.get_all_alerts()), 1)
        stored = self.database.get_alert_by_id("lifecycle-alert")
        self.assertEqual(stored["status"], "resolved")
        event_types = {event["event_type"] for event in self.database.get_alert_events()}
        self.assertTrue({"pending_started", "confirmed", "recovery_started", "resolved"}.issubset(event_types))
        restored = self.database.load_anomaly_states()[(signal, target)]
        self.assertEqual(restored["status"], "RESOLVED")
        self.assertIsNotNone(restored["cooldown_until"])

    def test_database_deduplicates_concurrent_confirmations_for_same_target(self):
        signal = "backend_process_memory_mb"
        target = "fastapi_process"
        first = self.make_alert(signal, target, "first-alert")
        first_state = initial_state(signal, target)
        first_state.update({
            "status": "CONFIRMED",
            "active_alert_id": first["alert_id"],
            "last_processed_sample": first["confirmed_at"],
        })
        self.database.persist_engine_updates([{
            "state": first_state,
            "alert": first,
            "events": [{"event_type": "confirmed", "alert": first}],
        }])

        duplicate = self.make_alert(signal, target, "duplicate-alert")
        duplicate_state = initial_state(signal, target)
        duplicate_state.update({
            "status": "CONFIRMED",
            "active_alert_id": duplicate["alert_id"],
            "last_processed_sample": duplicate["confirmed_at"],
        })
        self.database.persist_engine_updates([{
            "state": duplicate_state,
            "alert": duplicate,
            "events": [{"event_type": "confirmed", "alert": duplicate}],
        }])

        self.assertEqual(len(self.database.get_all_alerts()), 1)
        self.assertEqual(duplicate_state["active_alert_id"], "first-alert")
        self.assertEqual(duplicate_state["status"], "CONFIRMED")
        self.assertIn(
            "duplicate_suppressed",
            {event["event_type"] for event in self.database.get_alert_events()},
        )

    def test_restart_restores_multiple_signals_and_all_lifecycle_states(self):
        cpu = initial_state("backend_cpu_percent", "fastapi_process")
        pending = initial_state("average_latency_ms", "fastapi_http_service")
        pending.update({"status": "PENDING", "pending_since": "2026-10-31T12:00:00+00:00"})
        recovering = initial_state("system_memory_percent", "host_system")
        recovering.update({
            "status": "RECOVERING",
            "recovery_since": "2026-10-31T12:00:05+00:00",
            "active_alert_id": "system-alert",
        })
        resolved = initial_state("application_health", "fastapi_application")
        resolved.update({"status": "RESOLVED", "cooldown_until": "2026-10-31T12:10:00+00:00"})
        process_alert = self.make_alert("backend_process_memory_mb", "fastapi_process", "rss-alert")
        system_alert = self.make_alert("system_memory_percent", "host_system", "system-alert")
        cpu_alert = self.make_alert("backend_cpu_percent", "fastapi_process", "cpu-alert")
        health_alert = self.make_alert("application_health", "fastapi_application", "health-alert")
        http_alert = self.make_alert("http_5xx_error_rate_percent", "fastapi_http_service", "http-alert")
        states = [cpu, pending, recovering, resolved]
        self.database.persist_engine_updates([
            {"state": state, "events": []} for state in states
        ] + [
            {"state": initial_state(process_alert["signal"], process_alert["target_id"]),
             "alert": process_alert, "events": []},
            {"state": recovering, "alert": system_alert, "events": []},
            {"state": initial_state(cpu_alert["signal"], cpu_alert["target_id"]),
             "alert": cpu_alert, "events": []},
            {"state": initial_state(health_alert["signal"], health_alert["target_id"]),
             "alert": health_alert, "events": []},
            {"state": initial_state(http_alert["signal"], http_alert["target_id"]),
             "alert": http_alert, "events": []},
        ])

        loaded = self.database.load_anomaly_states()
        restored = restore_states(
            POLICIES, loaded, self.database.get_active_alerts()
        )
        self.assertEqual(restored[("backend_cpu_percent", "fastapi_process")]["active_alert_id"], "cpu-alert")
        self.assertEqual(restored[("backend_process_memory_mb", "fastapi_process")]["active_alert_id"], "rss-alert")
        self.assertEqual(restored[("backend_cpu_percent", "fastapi_process")]["active_alert_id"], "cpu-alert")
        self.assertEqual(restored[("application_health", "fastapi_application")]["active_alert_id"], "health-alert")
        self.assertEqual(restored[("http_5xx_error_rate_percent", "fastapi_http_service")]["active_alert_id"], "http-alert")
        self.assertEqual(restored[("system_memory_percent", "host_system")]["status"], "RECOVERING")
        self.assertEqual(restored[("system_memory_percent", "host_system")]["recovery_since"], recovering["recovery_since"])
        self.assertEqual(restored[("average_latency_ms", "fastapi_http_service")]["status"], "PENDING")
        self.assertEqual(restored[("application_health", "fastapi_application")]["active_alert_id"], "health-alert")
        self.assertEqual(len(self.database.get_active_alerts()), 5)
        self.assertEqual(
            len({alert["alert_id"] for alert in self.database.get_active_alerts()}), 5
        )

    def test_restart_preserves_unknown_and_resolved_policy_states(self):
        unknown = initial_state("average_latency_ms", "fastapi_http_service")
        unknown.update({
            "metric_status": "unknown",
            "unknown_reason": "stale latency window",
            "updated_at": "2026-10-31T12:00:00+00:00",
        })
        resolved = initial_state("application_health", "fastapi_application")
        resolved.update({
            "status": "RESOLVED",
            "cooldown_until": "2026-10-31T12:10:00+00:00",
            "metric_status": "ok",
        })
        self.database.persist_engine_updates([
            {"state": unknown, "events": []},
            {"state": resolved, "events": []},
        ])
        restored = restore_states(
            POLICIES,
            self.database.load_anomaly_states(),
            self.database.get_active_alerts(),
        )
        latency = restored[("average_latency_ms", "fastapi_http_service")]
        health = restored[("application_health", "fastapi_application")]
        self.assertEqual(latency["metric_status"], "unknown")
        self.assertEqual(latency["unknown_reason"], "stale latency window")
        self.assertEqual(health["status"], "RESOLVED")
        self.assertEqual(health["cooldown_until"], "2026-10-31T12:10:00+00:00")


if __name__ == "__main__":
    unittest.main()
