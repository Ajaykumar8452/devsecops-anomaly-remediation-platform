"""SQLite persistence for multi-signal anomaly state and alert history."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(
    os.environ.get("ALERT_DATABASE_PATH", PROJECT_DIR / "data" / "alerts.db")
)


class AlertDatabaseError(RuntimeError):
    """Raised when alert persistence or retrieval fails."""


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _connect(timeout_seconds=10):
    try:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(DATABASE_PATH), timeout=max(0.0, float(timeout_seconds))
        )
        connection.row_factory = sqlite3.Row
        return connection
    except (OSError, sqlite3.Error) as exc:
        raise AlertDatabaseError(f"Could not open alert database: {exc}") from exc


@contextmanager
def _transaction(timeout_seconds=10):
    connection = _connect(timeout_seconds=timeout_seconds)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database():
    """Create or non-destructively migrate all anomaly persistence tables."""
    try:
        with _transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    signal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    observed_value REAL NOT NULL,
                    threshold REAL NOT NULL,
                    started_at TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL,
                    resolved_at TEXT,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    target_id TEXT NOT NULL DEFAULT 'fastapi_process',
                    recovery_threshold REAL,
                    policy_mode TEXT NOT NULL DEFAULT 'enabled',
                    dedupe_key TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(alerts)")
            }
            additions = {
                "target_id": "TEXT NOT NULL DEFAULT 'fastapi_process'",
                "recovery_threshold": "REAL",
                "policy_mode": "TEXT NOT NULL DEFAULT 'enabled'",
                "dedupe_key": "TEXT",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE alerts ADD COLUMN {name} {definition}"
                    )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status)"
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_active_dedupe
                ON alerts(dedupe_key) WHERE dedupe_key IS NOT NULL AND status = 'confirmed'
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS anomaly_states (
                    signal TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pending_since TEXT,
                    recovery_since TEXT,
                    last_processed_sample TEXT,
                    active_alert_id TEXT,
                    cooldown_until TEXT,
                    cooldown_suppressed INTEGER NOT NULL DEFAULT 0,
                    metric_status TEXT NOT NULL DEFAULT 'unknown',
                    metric_timestamp TEXT,
                    observed_value REAL,
                    updated_at TEXT NOT NULL,
                    unknown_reason TEXT,
                    PRIMARY KEY (signal, target_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT,
                    signal TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    observed_value REAL,
                    details_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
    except sqlite3.Error as exc:
        raise AlertDatabaseError(f"Could not initialize alert database: {exc}") from exc


def save_alert(alert):
    """Insert a newly confirmed alert."""
    now = _utc_now()
    try:
        with _transaction() as connection:
            connection.execute(
                """
                INSERT INTO alerts (
                    alert_id, signal, status, observed_value, threshold,
                    started_at, confirmed_at, resolved_at, message,
                    created_at, updated_at, target_id, recovery_threshold,
                    policy_mode, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert["alert_id"], alert["signal"], alert["status"],
                    float(alert["observed_value"]), float(alert["threshold"]),
                    alert["started_at"], alert["confirmed_at"],
                    alert.get("resolved_at"), alert["message"], now, now,
                    alert.get("target_id", "fastapi_process"),
                    alert.get("recovery_threshold"),
                    alert.get("policy_mode", "enabled"),
                    alert.get("dedupe_key"),
                ),
            )
    except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        raise AlertDatabaseError(f"Could not save alert: {exc}") from exc


def resolve_alert(alert_id, resolved_at):
    """Resolve an active alert in place. Return True if it was updated."""
    try:
        with _transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE alerts
                SET status = 'resolved', resolved_at = ?, updated_at = ?, dedupe_key = NULL
                WHERE alert_id = ? AND status = 'confirmed'
                """,
                (resolved_at, _utc_now(), alert_id),
            )
            return cursor.rowcount == 1
    except sqlite3.Error as exc:
        raise AlertDatabaseError(f"Could not resolve alert {alert_id}: {exc}") from exc


def _as_dict(row):
    if row is None:
        return None
    return dict(row)


def get_alert_by_id(alert_id):
    try:
        with _transaction() as connection:
            row = connection.execute(
                "SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)
            ).fetchone()
        return _as_dict(row)
    except sqlite3.Error as exc:
        raise AlertDatabaseError(f"Could not retrieve alert {alert_id}: {exc}") from exc


def get_all_alerts(limit=500):
    try:
        with _transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM alerts ORDER BY confirmed_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [_as_dict(row) for row in rows]
    except (sqlite3.Error, TypeError, ValueError) as exc:
        raise AlertDatabaseError(f"Could not retrieve alert history: {exc}") from exc


def get_active_alerts():
    try:
        with _transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM alerts WHERE status = 'confirmed' ORDER BY confirmed_at DESC"
            ).fetchall()
        return [_as_dict(row) for row in rows]
    except sqlite3.Error as exc:
        raise AlertDatabaseError(f"Could not retrieve active alerts: {exc}") from exc


def _upsert_state(connection, state):
    connection.execute(
        """
        INSERT INTO anomaly_states (
            signal, target_id, status, pending_since, recovery_since,
            last_processed_sample, active_alert_id, cooldown_until,
            cooldown_suppressed, metric_status, metric_timestamp,
            observed_value, updated_at, unknown_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(signal, target_id) DO UPDATE SET
            status=excluded.status,
            pending_since=excluded.pending_since,
            recovery_since=excluded.recovery_since,
            last_processed_sample=excluded.last_processed_sample,
            active_alert_id=excluded.active_alert_id,
            cooldown_until=excluded.cooldown_until,
            cooldown_suppressed=excluded.cooldown_suppressed,
            metric_status=excluded.metric_status,
            metric_timestamp=excluded.metric_timestamp,
            observed_value=excluded.observed_value,
            updated_at=excluded.updated_at,
            unknown_reason=excluded.unknown_reason
        """,
        (
            state["signal"], state["target_id"], state["status"],
            state.get("pending_since"), state.get("recovery_since"),
            state.get("last_processed_sample"), state.get("active_alert_id"),
            state.get("cooldown_until"), int(bool(state.get("cooldown_suppressed"))),
            state.get("metric_status", "unknown"), state.get("metric_timestamp"),
            state.get("observed_value"), state.get("updated_at") or _utc_now(),
            state.get("unknown_reason"),
        ),
    )


def persist_engine_updates(updates):
    """Atomically persist state updates, alert lifecycle, and event records.

    Each update is a mapping with ``state``, optional ``alert`` (new confirmed
    alert), optional ``resolve`` (alert_id and resolved_at), and ``events``.
    """
    try:
        with _transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for update in updates:
                state = update["state"]
                alert = update.get("alert")
                resolution = update.get("resolve")
                if alert:
                    dedupe_key = f"{alert['signal']}:{alert.get('target_id', state['target_id'])}"
                    existing = connection.execute(
                        """
                        SELECT alert_id FROM alerts
                        WHERE status = 'confirmed'
                          AND (dedupe_key = ? OR (signal = ? AND target_id = ?))
                        ORDER BY confirmed_at DESC LIMIT 1
                        """,
                        (
                            dedupe_key,
                            alert["signal"],
                            alert.get("target_id", state["target_id"]),
                        ),
                    ).fetchone()
                    if existing:
                        state["status"] = "CONFIRMED"
                        state["pending_since"] = None
                        state["recovery_since"] = None
                        state["active_alert_id"] = existing["alert_id"]
                        update["events"] = [
                            {
                                "event_type": "duplicate_suppressed",
                                "alert_id": existing["alert_id"],
                            }
                            if event.get("event_type") == "confirmed"
                            else event
                            for event in update.get("events", [])
                        ]
                        alert = None
                    else:
                        alert["dedupe_key"] = dedupe_key
                if alert:
                    now = _utc_now()
                    connection.execute(
                        """
                        INSERT INTO alerts (
                            alert_id, signal, status, observed_value, threshold,
                            started_at, confirmed_at, resolved_at, message,
                            created_at, updated_at, target_id,
                            recovery_threshold, policy_mode, dedupe_key
                        ) VALUES (?, ?, 'confirmed', ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            alert["alert_id"], alert["signal"],
                            float(alert["observed_value"]), float(alert["threshold"]),
                            alert["started_at"], alert["confirmed_at"],
                            alert["message"], now, now,
                            alert.get("target_id", state["target_id"]),
                            alert.get("recovery_threshold"),
                            alert.get("policy_mode", "observation"),
                            alert.get("dedupe_key"),
                        ),
                    )
                if resolution:
                    cursor = connection.execute(
                        """
                        UPDATE alerts
                        SET status='resolved', resolved_at=?, updated_at=?, dedupe_key=NULL
                        WHERE alert_id=? AND signal=? AND target_id=? AND status='confirmed'
                        """,
                        (
                            resolution["resolved_at"], _utc_now(),
                            resolution["alert_id"], state["signal"], state["target_id"],
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise AlertDatabaseError(
                            f"Active alert {resolution['alert_id']} was not updated"
                        )
                _upsert_state(connection, state)
                for event in update.get("events", []):
                    alert_id = (
                        alert["alert_id"] if event.get("event_type") == "confirmed"
                        else event.get("alert_id") or state.get("active_alert_id")
                    )
                    details = {key: value for key, value in event.items() if key != "alert"}
                    connection.execute(
                        """
                        INSERT INTO alert_events (
                            alert_id, signal, target_id, event_type,
                            occurred_at, observed_value, details_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            alert_id, state["signal"], state["target_id"],
                            event["event_type"],
                            event.get("occurred_at", state.get("updated_at") or _utc_now()),
                            state.get("observed_value"),
                            json.dumps(details, default=str),
                        ),
                    )
    except AlertDatabaseError:
        raise
    except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        raise AlertDatabaseError(f"Could not persist anomaly transition: {exc}") from exc


def get_anomaly_states():
    try:
        with _transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM anomaly_states ORDER BY signal, target_id"
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["cooldown_suppressed"] = bool(item["cooldown_suppressed"])
            results.append(item)
        return results
    except sqlite3.Error as exc:
        raise AlertDatabaseError(f"Could not retrieve anomaly states: {exc}") from exc


def load_anomaly_states():
    """Return evaluator states keyed by their signal and target identity."""
    return {
        (state["signal"], state["target_id"]): state
        for state in get_anomaly_states()
    }


def get_alert_events(limit=1000):
    try:
        with _transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM alert_events ORDER BY event_id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            results.append(item)
        return results
    except (sqlite3.Error, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AlertDatabaseError(f"Could not retrieve alert events: {exc}") from exc


def check_database(timeout_seconds=1):
    """Return True when SQLite can execute a trivial read within a timeout."""
    try:
        with _transaction(timeout_seconds=timeout_seconds) as connection:
            connection.execute("SELECT 1").fetchone()
        return True
    except AlertDatabaseError:
        raise
    except sqlite3.Error as exc:
        raise AlertDatabaseError(f"Could not check alert database: {exc}") from exc
