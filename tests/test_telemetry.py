"""Unit tests for Telemetry Agent and Collector."""

import time
import pytest
from backend.telemetry_agent import TelemetryAgent
from controller.adaptive_engine import AdaptiveEngine
from controller.telemetry_collector import TelemetryCollector


def test_telemetry_agent_and_collector():
    # 1. Start TelemetryAgent on localhost port 9991
    agent = TelemetryAgent("h2", "127.0.0.1", 9991)
    agent.start()

    # Update some metrics
    agent.update_metrics(active_connections=3, raw_latency_ms=25.0)

    # 2. Setup Engine and Collector
    engine = AdaptiveEngine()
    engine.register_backend("h2", "127.0.0.1", "00:00:00:00:00:02", 8000, 9991, 2)
    collector = TelemetryCollector(engine, probe_interval=0.5, timeout=1.0)

    try:
        # Query agent directly
        payload = collector.poll_backend("h2", "127.0.0.1", 9991)
        assert payload is not None
        assert payload["server_id"] == "h2"
        assert payload["active_connections"] == 3
        assert payload["status"] == "HEALTHY"

        # Verify engine was updated
        backend = engine.backends["h2"]
        assert backend.active_connections == 3

    finally:
        agent.stop()


def test_telemetry_probe_failure():
    engine = AdaptiveEngine(max_consecutive_failures=2)
    engine.register_backend("h2", "127.0.0.1", "00:00:00:00:00:02", 8000, 9998, 2)
    collector = TelemetryCollector(engine, probe_interval=0.5, timeout=0.5)

    # Port 9998 is not listening -> should fail
    res1 = collector.poll_backend("h2", "127.0.0.1", 9998)
    assert res1 is None
    assert engine.backends["h2"].consecutive_failures == 1

    res2 = collector.poll_backend("h2", "127.0.0.1", 9998)
    assert res2 is None
    assert engine.backends["h2"].consecutive_failures == 2
    assert engine.backends["h2"].health_status == "UNHEALTHY"
