from __future__ import annotations

import argparse
import json
import logging
import random
import socket
import threading
import time
from typing import Optional

from backend.telemetry_agent import TelemetryAgent

logger = logging.getLogger("backend_server")


class BackendServer:
    def __init__(
        self,
        server_id: str,
        ip: str,
        service_port: int,
        telemetry_port: int,
        processing_delay_ms: float = 20.0,
        error_rate: float = 0.0,
        capacity: int = 100,
        telemetry_ip: Optional[str] = None,
    ):
        self.server_id = server_id
        self.ip = ip
        self.telemetry_ip = telemetry_ip or ip
        self.service_port = service_port
        self.telemetry_port = telemetry_port
        self.processing_delay_ms = processing_delay_ms
        self.error_rate = error_rate
        self.capacity = capacity

        self.running = False
        self.service_sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self.telemetry = TelemetryAgent(server_id, self.telemetry_ip, telemetry_port)

        self.current_connections = 0
        self._conn_lock = threading.Lock()

    def set_processing_delay(self, delay_ms: float) -> None:
        delay_ms = max(0.0, float(delay_ms))
        logger.info("[%s] Processing delay %.1f ms -> %.1f ms", self.server_id, self.processing_delay_ms, delay_ms)
        self.processing_delay_ms = delay_ms

    def set_error_rate(self, error_rate: float) -> None:
        error_rate = max(0.0, min(1.0, float(error_rate)))
        logger.info("[%s] Error rate %.3f -> %.3f", self.server_id, self.error_rate, error_rate)
        self.error_rate = error_rate

    def start(self) -> None:
        if self.running:
            return

        self._start_service()
        try:
            self.telemetry.start()
        except Exception:
            self._close_service()
            raise

        self.telemetry_port = self.telemetry.port
        self.running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True, name=f"worker-{self.server_id}")
        self._thread.start()
        logger.info(
            "Backend %s listening on %s:%s (delay %.1f ms)",
            self.server_id,
            self.ip,
            self.service_port,
            self.processing_delay_ms,
        )

    def stop(self) -> None:
        self.running = False
        self.telemetry.stop()
        self._close_service()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        logger.info("Backend %s stopped", self.server_id)

    def _start_service(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.ip, self.service_port))
        except OSError:
            if self.service_port == 0:
                sock.close()
                raise
            sock.bind((self.ip, 0))

        self.service_port = sock.getsockname()[1]
        sock.listen(self.capacity)
        self.service_sock = sock

    def _close_service(self) -> None:
        if self.service_sock:
            try:
                self.service_sock.close()
            except OSError:
                pass
            self.service_sock = None

    def _accept_loop(self) -> None:
        while self.running:
            sock = self.service_sock
            if not sock:
                break
            try:
                client_sock, addr = sock.accept()
            except OSError:
                if not self.running:
                    break
                continue

            with self._conn_lock:
                self.current_connections += 1
                active_now = self.current_connections
            self.telemetry.update_metrics(active_connections=active_now)

            threading.Thread(
                target=self._handle_request,
                args=(client_sock, addr),
                daemon=True,
            ).start()

    def _handle_request(self, sock: socket.socket, addr: tuple) -> None:
        start_time = time.perf_counter()
        received = False
        is_error = False

        try:
            sock.settimeout(10.0)
            data = sock.recv(2048)
            if not data:
                return

            received = True
            delay_sec = max(0.001, (self.processing_delay_ms + random.uniform(-2.0, 2.0)) / 1000.0)
            time.sleep(delay_sec)

            if random.random() < self.error_rate:
                is_error = True
                payload = {
                    "server_id": self.server_id,
                    "status": "ERROR_500",
                    "message": "Internal processing failure",
                }
                status = "HTTP/1.1 500 Internal Server Error\r\n"
            else:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                payload = {
                    "server_id": self.server_id,
                    "status": "SUCCESS",
                    "latency_ms": round(elapsed_ms, 2),
                    "active_conns": self.current_connections,
                }
                status = "HTTP/1.1 200 OK\r\n"

            body = json.dumps(payload)
            response = (
                f"{status}"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
                f"{body}"
            )
            sock.sendall(response.encode("utf-8"))

        except OSError as exc:
            logger.debug("[%s] Connection error: %s", self.server_id, exc)
            is_error = True
        finally:
            try:
                sock.close()
            except OSError:
                pass

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            with self._conn_lock:
                self.current_connections = max(0, self.current_connections - 1)
                active_now = self.current_connections

            if received:
                self.telemetry.update_metrics(
                    active_connections=active_now,
                    raw_latency_ms=duration_ms,
                    is_error=is_error,
                )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="SDN backend TCP server")
    parser.add_argument("--id", required=True, help="server ID, for example h2")
    parser.add_argument("--ip", default="0.0.0.0", help="bind address")
    parser.add_argument("--port", type=int, default=8000, help="service port")
    parser.add_argument("--telemetry-port", type=int, default=0, help="telemetry port")
    parser.add_argument("--telemetry-ip", default=None, help="optional telemetry bind address")
    parser.add_argument("--delay", type=float, default=20.0, help="processing delay in ms")
    parser.add_argument("--error-rate", type=float, default=0.0, help="error rate from 0.0 to 1.0")
    args = parser.parse_args()

    server = BackendServer(
        server_id=args.id,
        ip=args.ip,
        service_port=args.port,
        telemetry_port=args.telemetry_port,
        telemetry_ip=args.telemetry_ip,
        processing_delay_ms=args.delay,
        error_rate=args.error_rate,
    )
    server.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
