"""Unit tests for Backend Server and TCP Client."""

import time
import pytest
from backend.server import BackendServer
from client.client import TcpClient


def test_backend_server_and_client():
    server = BackendServer(
        server_id="h2",
        ip="127.0.0.1",
        service_port=8080,
        telemetry_port=9080,
        processing_delay_ms=10.0,
        error_rate=0.0,
    )
    server.start()
    client = TcpClient(vip="127.0.0.1", port=8080, timeout=2.0)

    try:
        # Give server time to bind
        time.sleep(0.2)
        success, s_id, lat, msg = client.send_request({"test": 1})
        assert success is True
        assert s_id == "h2"
        assert lat >= 8.0  # Latency should reflect the 10ms simulated processing delay

        # Verify telemetry recorded the request
        payload = server.telemetry.get_payload()
        assert payload["total_requests"] == 1
        assert payload["failed_requests"] == 0

    finally:
        server.stop()


def test_backend_error_injection():
    server = BackendServer(
        server_id="h3",
        ip="127.0.0.1",
        service_port=8081,
        telemetry_port=9081,
        processing_delay_ms=5.0,
        error_rate=1.0,  # 100% simulated error
    )
    server.start()
    client = TcpClient(vip="127.0.0.1", port=8081, timeout=2.0)

    try:
        time.sleep(0.2)
        success, s_id, lat, msg = client.send_request({"test": 2})
        assert success is False
        assert "500" in msg

        payload = server.telemetry.get_payload()
        assert payload["total_requests"] == 1
        assert payload["failed_requests"] == 1
        assert payload["error_rate"] == 1.0

    finally:
        server.stop()
