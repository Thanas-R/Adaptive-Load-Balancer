import time

import pytest

from controller.adaptive_engine import AdaptiveEngine


def test_initialization_and_weights():
    engine = AdaptiveEngine(
        weights={"active_connections": 50, "smoothed_latency": 35, "error_rate": 15}
    )
    assert engine.weights["active_connections"] == pytest.approx(0.50)
    assert engine.weights["smoothed_latency"] == pytest.approx(0.35)
    assert engine.weights["error_rate"] == pytest.approx(0.15)


def test_ema_smoothing():
    engine = AdaptiveEngine(ema_alpha=0.25)
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2, initial_delay_ms=20.0)

    backend = engine.backends["h2"]
    assert backend.smoothed_latency_ms == 20.0

    engine.update_telemetry("h2", {"raw_latency_ms": 100.0})
    assert backend.smoothed_latency_ms == pytest.approx(40.0)

    engine.update_telemetry("h2", {"raw_latency_ms": 100.0})
    assert backend.smoothed_latency_ms == pytest.approx(55.0)


def test_scoring_and_selection():
    engine = AdaptiveEngine(
        weights={"active_connections": 0.50, "smoothed_latency": 0.35, "error_rate": 0.15}
    )
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2, initial_delay_ms=20.0)
    engine.register_backend("h3", "10.0.0.3", "00:00:00:00:00:03", 8000, 9003, 3, initial_delay_ms=20.0)
    engine.register_backend("h4", "10.0.0.4", "00:00:00:00:00:04", 8000, 9004, 4, initial_delay_ms=20.0)

    engine.update_telemetry("h2", {"active_connections": 2, "smoothed_latency_ms": 15.0, "error_rate": 0.0})
    engine.update_telemetry("h3", {"active_connections": 10, "smoothed_latency_ms": 25.0, "error_rate": 0.0})
    engine.update_telemetry("h4", {"active_connections": 5, "smoothed_latency_ms": 200.0, "error_rate": 0.0})

    scores = engine.calculate_scores()
    assert scores["h2"][0] < scores["h3"][0]
    assert scores["h2"][0] < scores["h4"][0]
    assert engine.select_backend().server_id == "h2"
    assert engine.select_backend(exclude={"h2"}).server_id in ("h3", "h4")


def test_health_state_transitions():
    engine = AdaptiveEngine(max_consecutive_failures=3, recovery_cooldown_sec=1.0)
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2)
    engine.update_telemetry("h2", {"active_connections": 0})

    assert engine.backends["h2"].health_status == "HEALTHY"

    engine.record_probe_failure("h2")
    engine.record_probe_failure("h2")
    assert engine.backends["h2"].health_status == "HEALTHY"

    engine.record_probe_failure("h2")
    assert engine.backends["h2"].health_status == "UNHEALTHY"
    assert engine.get_eligible_backends() == []

    engine.update_telemetry("h2", {"active_connections": 0})
    assert engine.backends["h2"].health_status == "RECOVERING"

    time.sleep(1.1)
    engine.update_telemetry("h2", {"active_connections": 0})
    assert engine.backends["h2"].health_status == "HEALTHY"


def test_unseen_backend_is_not_marked_unhealthy():
    engine = AdaptiveEngine(max_consecutive_failures=1)
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2)

    engine.record_probe_failure("h2")

    assert engine.backends["h2"].health_status == "HEALTHY"


def test_in_flight_is_capped_by_telemetry():
    engine = AdaptiveEngine()
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2)

    for _ in range(5):
        engine.select_backend()

    assert engine.backends["h2"].in_flight == 5

    engine.update_telemetry("h2", {"active_connections": 1})

    assert engine.backends["h2"].in_flight == 1


def test_round_robin_selection():
    engine = AdaptiveEngine(mode="round_robin")
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2)
    engine.register_backend("h3", "10.0.0.3", "00:00:00:00:00:03", 8000, 9003, 3)

    picks = [engine.select_backend().server_id for _ in range(4)]
    assert picks == ["h2", "h3", "h2", "h3"]
