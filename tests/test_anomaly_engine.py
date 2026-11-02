"""Deterministic unit tests for the shared anomaly state machine."""

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from core.anomaly_engine import advance_state, initial_state, mark_unknown
from core.anomaly_policy import POLICIES, condition_for


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.policy = replace(
            POLICIES["backend_process_memory_mb"],
            trigger_threshold=80.0,
            recovery_threshold=70.0,
            persistence_seconds=10,
            recovery_seconds=5,
            cooldown_seconds=20,
        )
        self.now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        self.state = initial_state(self.policy.signal, self.policy.target_id)
        self.ids = iter(["alert-one", "alert-two"])

    def test_policy_defaults_preserve_cpu_and_keep_new_signals_observation_only(self):
        cpu = POLICIES["backend_cpu_percent"]
        self.assertEqual(cpu.trigger_threshold, 80.0)
        self.assertEqual(cpu.recovery_threshold, 70.0)
        self.assertEqual(cpu.persistence_seconds, 60)
        self.assertEqual(cpu.recovery_seconds, 30)
        for signal in (
            "backend_process_memory_mb",
            "system_memory_percent",
            "application_health",
            "http_5xx_error_rate_percent",
            "average_latency_ms",
        ):
            self.assertEqual(POLICIES[signal].mode, "observation")
        self.assertEqual(POLICIES["backend_process_memory_mb"].trigger_threshold, 80.0)
        self.assertEqual(POLICIES["system_memory_percent"].trigger_threshold, 90.0)
        self.assertEqual(POLICIES["http_5xx_error_rate_percent"].trigger_threshold, 10.0)
        self.assertEqual(POLICIES["http_5xx_error_rate_percent"].min_samples, 5)
        self.assertEqual(POLICIES["average_latency_ms"].trigger_threshold, 500.0)

    def test_cpu_state_machine_keeps_verified_boundaries_and_durations(self):
        cpu_policy = POLICIES["backend_cpu_percent"]
        state = initial_state(cpu_policy.signal, cpu_policy.target_id)
        for seconds in (0, 59):
            state, _ = advance_state(
                state,
                triggered=True,
                recovered=False,
                sample_time=self.now + timedelta(seconds=seconds),
                observed_value=80.0,
                policy=cpu_policy,
                alert_id_factory=lambda: "cpu-boundary-alert",
            )
        self.assertEqual(state["status"], "PENDING")
        state, events = advance_state(
            state,
            triggered=True,
            recovered=False,
            sample_time=self.now + timedelta(seconds=60),
            observed_value=80.0,
            policy=cpu_policy,
            alert_id_factory=lambda: "cpu-boundary-alert",
        )
        self.assertEqual(state["status"], "CONFIRMED")
        self.assertEqual(sum(event["event_type"] == "confirmed" for event in events), 1)

        state, _ = advance_state(
            state,
            triggered=False,
            recovered=False,
            sample_time=self.now + timedelta(seconds=61),
            observed_value=70.0,
            policy=cpu_policy,
        )
        self.assertEqual(state["status"], "CONFIRMED")
        state, _ = advance_state(
            state,
            triggered=False,
            recovered=True,
            sample_time=self.now + timedelta(seconds=62),
            observed_value=69.9,
            policy=cpu_policy,
        )
        self.assertEqual(state["status"], "RECOVERING")
        state, _ = advance_state(
            state,
            triggered=False,
            recovered=True,
            sample_time=self.now + timedelta(seconds=91),
            observed_value=69.9,
            policy=cpu_policy,
        )
        self.assertEqual(state["status"], "RECOVERING")
        state, events = advance_state(
            state,
            triggered=False,
            recovered=True,
            sample_time=self.now + timedelta(seconds=92),
            observed_value=69.9,
            policy=cpu_policy,
        )
        self.assertEqual(state["status"], "RESOLVED")
        self.assertEqual(events[0]["event_type"], "resolved")

    def advance(self, seconds, value):
        triggered, recovered = condition_for(self.policy, value)
        self.state, events = advance_state(
            self.state,
            triggered=triggered,
            recovered=recovered,
            sample_time=self.now + timedelta(seconds=seconds),
            observed_value=value,
            policy=self.policy,
            alert_id_factory=lambda: next(self.ids),
        )
        return events

    def test_normal_conditions_stay_normal(self):
        self.assertEqual(self.advance(0, 50), [])
        self.assertEqual(self.state["status"], "NORMAL")

    def test_short_spike_does_not_confirm(self):
        self.advance(0, 90)
        self.assertEqual(self.state["status"], "PENDING")
        events = self.advance(4, 50)
        self.assertEqual(self.state["status"], "NORMAL")
        self.assertNotIn("confirmed", [event["event_type"] for event in events])

    def test_sustained_anomaly_confirms_once_and_recovers(self):
        self.advance(0, 90)
        events = self.advance(10, 90)
        confirmed = [event for event in events if event["event_type"] == "confirmed"]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0]["alert"]["alert_id"], "alert-one")
        self.assertEqual(self.state["status"], "CONFIRMED")
        self.assertEqual(self.advance(11, 90), [])

        self.advance(12, 60)
        self.assertEqual(self.state["status"], "RECOVERING")
        events = self.advance(17, 60)
        resolved = [event for event in events if event["event_type"] == "resolved"]
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["alert_id"], "alert-one")
        self.assertEqual(self.state["status"], "RESOLVED")

    def test_recovery_resets_if_anomaly_returns(self):
        self.advance(0, 90)
        self.advance(10, 90)
        self.advance(11, 60)
        self.assertEqual(self.state["status"], "RECOVERING")
        self.advance(13, 90)
        self.assertEqual(self.state["status"], "CONFIRMED")
        self.assertIsNone(self.state["recovery_since"])

    def test_cooldown_suppresses_duplicate_then_allows_new_episode(self):
        self.advance(0, 90)
        self.advance(10, 90)
        self.advance(11, 60)
        self.advance(16, 60)
        events = self.advance(17, 90)
        self.assertEqual(self.state["status"], "RESOLVED")
        self.assertIn("cooldown_suppressed", [event["event_type"] for event in events])
        self.advance(36, 50)
        self.advance(37, 90)
        events = self.advance(47, 90)
        confirmed = [event for event in events if event["event_type"] == "confirmed"]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0]["alert"]["alert_id"], "alert-two")

    def test_unknown_metric_does_not_clear_state(self):
        self.advance(0, 90)
        self.advance(10, 90)
        self.assertEqual(self.state["status"], "CONFIRMED")
        active_alert_id = self.state["active_alert_id"]
        before = dict(self.state)
        unknown = mark_unknown(
            self.state,
            now=self.now + timedelta(seconds=20),
            reason="sample stale",
        )
        self.assertEqual(unknown["status"], before["status"])
        self.assertEqual(unknown["pending_since"], before["pending_since"])
        self.assertEqual(unknown["active_alert_id"], active_alert_id)
        self.assertEqual(unknown["metric_status"], "unknown")
        resumed, events = advance_state(
            unknown,
            triggered=True,
            recovered=False,
            sample_time=self.now + timedelta(seconds=21),
            observed_value=90,
            policy=self.policy,
        )
        self.assertEqual(resumed["status"], "CONFIRMED")
        self.assertEqual(resumed["active_alert_id"], active_alert_id)
        self.assertEqual(resumed["metric_status"], "ok")
        self.assertFalse(any(event["event_type"] == "confirmed" for event in events))

    def test_all_six_signals_follow_independent_full_lifecycles(self):
        bad_values = {
            "application_health": False,
        }
        recovery_values = {
            "application_health": True,
        }
        for signal, source_policy in POLICIES.items():
            with self.subTest(signal=signal):
                policy = replace(
                    source_policy,
                    persistence_seconds=10,
                    recovery_seconds=5,
                    cooldown_seconds=20,
                )
                trigger_value = bad_values.get(signal, policy.trigger_threshold)
                recovery_value = recovery_values.get(
                    signal,
                    (policy.recovery_threshold - 1)
                    if policy.recovery_inclusive
                    else (policy.recovery_threshold - 0.1),
                )
                state = initial_state(signal, policy.target_id)
                normal_value = (
                    True if signal == "application_health"
                    else policy.recovery_threshold - 1
                )
                normal_trigger, normal_recovered = condition_for(policy, normal_value)
                state, _ = advance_state(
                    state,
                    triggered=normal_trigger,
                    recovered=normal_recovered,
                    sample_time=self.now - timedelta(seconds=2),
                    observed_value=normal_value,
                    policy=policy,
                )
                self.assertEqual(state["status"], "NORMAL")

                # One brief breach must return to NORMAL without confirmation.
                triggered, recovered = condition_for(policy, trigger_value)
                state, _ = advance_state(
                    state,
                    triggered=triggered,
                    recovered=recovered,
                    sample_time=self.now,
                    observed_value=trigger_value,
                    policy=policy,
                )
                self.assertEqual(state["status"], "PENDING")
                state, spike_events = advance_state(
                    state,
                    triggered=normal_trigger,
                    recovered=normal_recovered,
                    sample_time=self.now + timedelta(seconds=1),
                    observed_value=normal_value,
                    policy=policy,
                )
                self.assertEqual(state["status"], "NORMAL")
                self.assertFalse(any(e["event_type"] == "confirmed" for e in spike_events))

                events = []
                for offset in (2, 11):
                    triggered, recovered = condition_for(policy, trigger_value)
                    state, events = advance_state(
                        state,
                        triggered=triggered,
                        recovered=recovered,
                        sample_time=self.now + timedelta(seconds=offset),
                        observed_value=trigger_value,
                        policy=policy,
                        alert_id_factory=lambda: f"{signal}-alert",
                    )
                self.assertEqual(state["status"], "PENDING")
                triggered, recovered = condition_for(policy, trigger_value)
                state, events = advance_state(
                    state,
                    triggered=triggered,
                    recovered=recovered,
                    sample_time=self.now + timedelta(seconds=12),
                    observed_value=trigger_value,
                    policy=policy,
                    alert_id_factory=lambda: f"{signal}-alert",
                )
                self.assertEqual(state["status"], "CONFIRMED")
                self.assertEqual(state["active_alert_id"], f"{signal}-alert")
                triggered, recovered = condition_for(policy, trigger_value)
                state, events = advance_state(
                    state,
                    triggered=triggered,
                    recovered=recovered,
                    sample_time=self.now + timedelta(seconds=13),
                    observed_value=trigger_value,
                    policy=policy,
                )
                self.assertFalse(any(e["event_type"] == "confirmed" for e in events))
                triggered, recovered = condition_for(policy, recovery_value)
                state, events = advance_state(
                    state,
                    triggered=triggered,
                    recovered=recovered,
                    sample_time=self.now + timedelta(seconds=14),
                    observed_value=recovery_value,
                    policy=policy,
                )
                self.assertEqual(state["status"], "RECOVERING")
                for offset in (18, 19):
                    state, events = advance_state(
                        state,
                        triggered=triggered,
                        recovered=recovered,
                        sample_time=self.now + timedelta(seconds=offset),
                        observed_value=recovery_value,
                        policy=policy,
                    )
                self.assertEqual(state["status"], "RESOLVED")
                self.assertEqual(events[0]["alert_id"], f"{signal}-alert")

    def test_independent_signal_states(self):
        second = initial_state("system_memory_percent", "host_system")
        triggered, recovered = condition_for(self.policy, 90)
        self.state, _ = advance_state(
            self.state,
            triggered=triggered,
            recovered=recovered,
            sample_time=self.now,
            observed_value=90,
            policy=self.policy,
        )
        self.assertEqual(self.state["status"], "PENDING")
        self.assertEqual(second["status"], "NORMAL")
        self.assertEqual(second["signal"], "system_memory_percent")


if __name__ == "__main__":
    unittest.main()
