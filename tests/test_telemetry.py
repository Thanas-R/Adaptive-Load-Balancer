import socket

from backend.telemetry_agent import TelemetryAgent
from controller.adaptive_engine import AdaptiveEngine
from controller.telemetry_collector import TelemetryCollector


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_telemetry_agent_and_collector():
    agent = TelemetryAgent("h2", "127.0.0.1", 0)
    agent.start()
    agent.update_metrics(active_connections=3, raw_latency_ms=25.0)

    engine = AdaptiveEngine()
    engine.register_backend("h2", "127.0.0.1", "00:00:00:00:00:02", 8000, agent.port, 2)
    collector = TelemetryCollector(engine, probe_interval=0.5, timeout=1.0)

    try:
        payload = collector.poll_backend("h2", "127.0.0.1", agent.port)
        assert payload is not None
        assert payload["server_id"] == "h2"
        assert payload["active_connections"] == 3
        assert payload["status"] == "HEALTHY"
        assert engine.backends["h2"].active_connections == 3
    finally:
        agent.stop()


def test_telemetry_probe_failure():
    port = free_port()
    engine = AdaptiveEngine(max_consecutive_failures=2)
    engine.register_backend("h2", "127.0.0.1", "00:00:00:00:00:02", 8000, port, 2)
    engine.update_telemetry("h2", {"active_connections": 0})
    collector = TelemetryCollector(engine, probe_interval=0.5, timeout=0.5)

    assert collector.poll_backend("h2", "127.0.0.1", port) is None
    assert engine.backends["h2"].consecutive_failures == 1

    assert collector.poll_backend("h2", "127.0.0.1", port) is None
    assert engine.backends["h2"].consecutive_failures == 2
    assert engine.backends["h2"].health_status == "UNHEALTHY"
