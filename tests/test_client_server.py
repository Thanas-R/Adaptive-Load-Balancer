import time

from backend.server import BackendServer
from client.client import TcpClient


def test_backend_server_and_client():
    server = BackendServer(
        server_id="h2",
        ip="127.0.0.1",
        service_port=0,
        telemetry_port=0,
        processing_delay_ms=10.0,
        error_rate=0.0,
    )
    server.start()
    client = TcpClient(vip="127.0.0.1", port=server.service_port, timeout=2.0)

    try:
        time.sleep(0.1)
        success, server_id, latency, message = client.send_request({"test": 1})
        assert success is True
        assert server_id == "h2"
        assert latency >= 8.0

        payload = server.telemetry.get_payload()
        assert payload["total_requests"] == 1
        assert payload["failed_requests"] == 0
    finally:
        server.stop()


def test_backend_error_injection():
    server = BackendServer(
        server_id="h3",
        ip="127.0.0.1",
        service_port=0,
        telemetry_port=0,
        processing_delay_ms=5.0,
        error_rate=1.0,
    )
    server.start()
    client = TcpClient(vip="127.0.0.1", port=server.service_port, timeout=2.0)

    try:
        time.sleep(0.1)
        success, server_id, latency, message = client.send_request({"test": 2})
        assert success is False
        assert "500" in message

        payload = server.telemetry.get_payload()
        assert payload["total_requests"] == 1
        assert payload["failed_requests"] == 1
        assert payload["error_rate"] == 1.0
    finally:
        server.stop()
