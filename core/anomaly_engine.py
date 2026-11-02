"""Deterministic state transitions shared by independent anomaly signals."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import uuid


def utc_iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_time(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def initial_state(signal, target_id):
    return {
        "signal": signal,
        "target_id": target_id,
        "status": "NORMAL",
        "pending_since": None,
        "recovery_since": None,
        "last_processed_sample": None,
        "active_alert_id": None,
        "cooldown_until": None,
        "cooldown_suppressed": False,
        "metric_status": "unknown",
        "metric_timestamp": None,
        "observed_value": None,
        "updated_at": None,
    }


def advance_state(
    state,
    *,
    triggered,
    recovered,
    sample_time,
    observed_value,
    policy,
    alert_id_factory=None,
    gap_detected=False,
):
    """Advance a state for one fresh sample; missing data must not call this.

    Returns ``(new_state, events)``. ``events`` can include an alert payload or
    resolution metadata; persistence is intentionally handled by the caller.
    ``sample_time`` is injectable, which keeps all timing deterministic in tests.
    """
    now = sample_time
    now_text = utc_iso(now)
    result = deepcopy(state)
    result["metric_status"] = "ok"
    result["metric_timestamp"] = now_text
    result["observed_value"] = observed_value
    result["last_processed_sample"] = now_text
    result["updated_at"] = now_text
    result.pop("unknown_reason", None)
    events = []
    status = result["status"]

    if gap_detected and status == "PENDING":
        result["pending_since"] = now_text
        events.append({"event_type": "pending_restarted_after_gap"})
    elif gap_detected and status == "RECOVERING":
        result["status"] = "CONFIRMED"
        result["recovery_since"] = None
        status = "CONFIRMED"
        events.append({"event_type": "recovery_reset_after_gap"})

    if status == "RESOLVED":
        cooldown_until = parse_time(result.get("cooldown_until"))
        if cooldown_until and now < cooldown_until:
            if triggered and not result.get("cooldown_suppressed"):
                events.append({"event_type": "cooldown_suppressed"})
                result["cooldown_suppressed"] = True
            return result, events
        result["status"] = "NORMAL"
        result["cooldown_suppressed"] = False
        status = "NORMAL"

    if status == "NORMAL":
        if triggered:
            result["status"] = "PENDING"
            result["pending_since"] = now_text
            result["recovery_since"] = None
            events.append({"event_type": "pending_started"})
        return result, events

    if status == "PENDING":
        if not triggered:
            result["status"] = "NORMAL"
            result["pending_since"] = None
            events.append({"event_type": "pending_cleared"})
            return result, events

        started = parse_time(result["pending_since"])
        elapsed = (now - started).total_seconds()
        if elapsed >= policy.persistence_seconds:
            new_alert_id = (alert_id_factory or (lambda: str(uuid.uuid4())))()
            result["status"] = "CONFIRMED"
            result["active_alert_id"] = new_alert_id
            result["recovery_since"] = None
            events.append({
                "event_type": "confirmed",
                "alert": {
                    "alert_id": new_alert_id,
                    "signal": policy.signal,
                    "target_id": policy.target_id,
                    "status": "confirmed",
                    "observed_value": observed_value,
                    "threshold": policy.trigger_threshold,
                    "recovery_threshold": policy.recovery_threshold,
                    "started_at": result["pending_since"],
                    "confirmed_at": now_text,
                    "resolved_at": None,
                    "message": policy.message,
                    "policy_mode": policy.mode,
                },
            })
        return result, events

    if status == "CONFIRMED":
        if recovered:
            result["status"] = "RECOVERING"
            result["recovery_since"] = now_text
            events.append({"event_type": "recovery_started"})
        return result, events

    if status == "RECOVERING":
        if not recovered:
            result["status"] = "CONFIRMED"
            result["recovery_since"] = None
            events.append({"event_type": "recovery_reset"})
            return result, events

        started = parse_time(result["recovery_since"])
        elapsed = (now - started).total_seconds()
        if elapsed >= policy.recovery_seconds:
            alert_id = result["active_alert_id"]
            result["status"] = "RESOLVED"
            result["pending_since"] = None
            result["recovery_since"] = None
            result["active_alert_id"] = None
            result["cooldown_until"] = utc_iso(
                now + timedelta(seconds=policy.cooldown_seconds)
            )
            result["cooldown_suppressed"] = False
            events.append({
                "event_type": "resolved",
                "alert_id": alert_id,
                "resolved_at": now_text,
            })
        return result, events

    # Unknown persisted states fail closed and require a fresh detection cycle.
    result.update(initial_state(policy.signal, policy.target_id))
    result["metric_status"] = "ok"
    result["metric_timestamp"] = now_text
    result["observed_value"] = observed_value
    result["last_processed_sample"] = now_text
    result["updated_at"] = now_text
    events.append({"event_type": "invalid_state_reset"})
    return result, events


def mark_unknown(state, *, now, reason):
    """Record metric staleness without changing detection or alert state."""
    result = deepcopy(state)
    result["metric_status"] = "unknown"
    result["metric_timestamp"] = None
    result["observed_value"] = None
    result["updated_at"] = utc_iso(now)
    result["unknown_reason"] = reason
    return result


def restore_states(policies, persisted_states, active_alerts):
    """Restore evaluator state by the persisted signal and target identity."""
    restored = {
        (policy.signal, policy.target_id): initial_state(
            policy.signal, policy.target_id
        )
        for policy in policies.values()
    }
    restored.update(persisted_states)

    # The most recently confirmed alert is the active episode for that
    # signal/target. Other signals remain independent.
    active_by_key = {}
    for alert in active_alerts:
        key = (alert["signal"], alert.get("target_id", "fastapi_process"))
        active_by_key.setdefault(key, alert)

    for key, alert in active_by_key.items():
        if key not in restored:
            continue
        state = restored[key]
        same_episode = state.get("active_alert_id") == alert["alert_id"]
        if not same_episode or state.get("status") not in {"CONFIRMED", "RECOVERING"}:
            state["pending_since"] = None
            state["recovery_since"] = None
            state["status"] = "CONFIRMED"
        state["active_alert_id"] = alert["alert_id"]
        state["signal"], state["target_id"] = key
    return restored
