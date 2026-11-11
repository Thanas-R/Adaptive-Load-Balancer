"""Unit tests for the AdaptiveEngine."""

import time
import pytest
from controller.adaptive_engine import AdaptiveEngine, BackendStats


def test_initialization_and_weights():
    engine = AdaptiveEngine(
        weights={"active_connections": 50, "smoothed_latency": 35, "error_rate": 15}
    )
    assert pytest.approx(engine.weights["active_connections"], 0.01) == 0.50
    assert pytest.approx(engine.weights["smoothed_latency"], 0.01) == 0.35
    assert pytest.approx(engine.weights["error_rate"], 0.01) == 0.15


def test_ema_smoothing():
    engine = AdaptiveEngine(ema_alpha=0.25)
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2, initial_delay_ms=20.0)

    # Initial EMA = 20.0
    backend = engine.backends["h2"]
    assert backend.smoothed_latency_ms == 20.0

    # First update: raw_latency = 100.0
    # EMA = 0.25 * 100 + 0.75 * 20 = 25 + 15 = 40.0
    engine.update_telemetry("h2", {"raw_latency_ms": 100.0})
    assert pytest.approx(backend.smoothed_latency_ms, 0.01) == 40.0

    # Second update: raw_latency = 100.0
    # EMA = 0.25 * 100 + 0.75 * 40 = 25 + 30 = 55.0
    engine.update_telemetry("h2", {"raw_latency_ms": 100.0})
    assert pytest.approx(backend.smoothed_latency_ms, 0.01) == 55.0


def test_scoring_and_selection():
    engine = AdaptiveEngine(
        weights={"active_connections": 0.50, "smoothed_latency": 0.35, "error_rate": 0.15}
    )
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2, initial_delay_ms=20.0)
    engine.register_backend("h3", "10.0.0.3", "00:00:00:00:00:03", 8000, 9003, 3, initial_delay_ms=20.0)
    engine.register_backend("h4", "10.0.0.4", "00:00:00:00:00:04", 8000, 9004, 4, initial_delay_ms=20.0)

    # Make h2 have low connections and low latency
    engine.update_telemetry("h2", {"active_connections": 2, "smoothed_latency_ms": 15.0, "error_rate": 0.0})
    # Make h3 have higher connections
    engine.update_telemetry("h3", {"active_connections": 10, "smoothed_latency_ms": 25.0, "error_rate": 0.0})
    # Make h4 have very high latency
    engine.update_telemetry("h4", {"active_connections": 5, "smoothed_latency_ms": 200.0, "error_rate": 0.0})

    scores = engine.calculate_scores()
    assert "h2" in scores and "h3" in scores and "h4" in scores

    # h2 should have the lowest score (best server)
    h2_score = scores["h2"][0]
    h3_score = scores["h3"][0]
    h4_score = scores["h4"][0]

    assert h2_score < h3_score
    assert h2_score < h4_score

    # Selection should pick h2
    chosen = engine.select_backend()
    assert chosen.server_id == "h2"


def test_health_state_transitions():
    engine = AdaptiveEngine(max_consecutive_failures=3, recovery_cooldown_sec=1.0)
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2)

    assert engine.backends["h2"].health_status == "HEALTHY"

    # 1st and 2nd failure - remains healthy
    engine.record_probe_failure("h2")
    assert engine.backends["h2"].health_status == "HEALTHY"
    engine.record_probe_failure("h2")
    assert engine.backends["h2"].health_status == "HEALTHY"

    # 3rd failure - transitions to UNHEALTHY
    engine.record_probe_failure("h2")
    assert engine.backends["h2"].health_status == "UNHEALTHY"

    # UNHEALTHY server should not be in eligible backends
    eligible = engine.get_eligible_backends()
    assert len(eligible) == 0

    # Heartbeat received - enters RECOVERING
    engine.update_telemetry("h2", {"active_connections": 0})
    assert engine.backends["h2"].health_status == "RECOVERING"

    # Still in cooldown
    time.sleep(1.1)
    # Next telemetry update after cooldown completes transitions to HEALTHY
    engine.update_telemetry("h2", {"active_connections": 0})
    assert engine.backends["h2"].health_status == "HEALTHY"


def test_round_robin_selection():
    engine = AdaptiveEngine(mode="round_robin")
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2)
    engine.register_backend("h3", "10.0.0.3", "00:00:00:00:00:03", 8000, 9003, 3)

    picks = [engine.select_backend().server_id for _ in range(4)]
    assert picks == ["h3", "h2", "h3", "h2"] or picks == ["h2", "h3", "h2", "h3"]
