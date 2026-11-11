"""TCP Socket Backend Server.

Multi-threaded worker server simulating realistic backend workloads.
Features:
- Configurable base processing delay and jitter
- Dynamic error rate injection
- Active connection tracking
- Integrated telemetry reporting
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import socket
import sys
import threading
import time
from typing import Optional

from backend.telemetry_agent import TelemetryAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
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
    ):
        # Server identification and networking parameters
        self.server_id = server_id
        self.ip = ip
        self.service_port = service_port
        self.telemetry_port = telemetry_port
        self.processing_delay_ms = processing_delay_ms
        self.error_rate = error_rate
        self.capacity = capacity

        # Lifecycle control
        self.running = False
        self.service_sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

        # Dedicated telemetry agent instance
        self.telemetry = TelemetryAgent(server_id, ip, telemetry_port)

        # Thread-safe active connection counter
        self.current_connections = 0
        self._conn_lock = threading.Lock()

    def set_processing_delay(self, delay_ms: float) -> None:
        # Dynamically adjust backend processing delay
        logger.info(f"[{self.server_id}] Processing delay updated from {self.processing_delay_ms}ms to {delay_ms}ms")
        self.processing_delay_ms = delay_ms

    def set_error_rate(self, error_rate: float) -> None:
        # Dynamically inject error probability
        logger.info(f"[{self.server_id}] Error rate updated from {self.error_rate} to {error_rate}")
        self.error_rate = error_rate

    def start(self) -> None:
        # Start telemetry agent service first
        self.running = True
        self.telemetry.start()

        # Bind and listen on TCP service socket
        self.service_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.service_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.service_sock.bind((self.ip, self.service_port))
        self.service_sock.listen(self.capacity)

        # Launch background accept thread
        self._thread = threading.Thread(target=self._accept_loop, daemon=True, name=f"Worker-{self.server_id}")
        self._thread.start()
        logger.info(f"Backend Server {self.server_id} listening on {self.ip}:{self.service_port} (Delay: {self.processing_delay_ms}ms)")

    def stop(self) -> None:
        # Gracefully shut down server and telemetry
        self.running = False
        self.telemetry.stop()
        if self.service_sock:
            try:
                self.service_sock.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info(f"Backend Server {self.server_id} stopped.")

    def _accept_loop(self) -> None:
        # Continuous loop accepting incoming TCP connections
        while self.running:
            try:
                sock, addr = self.service_sock.accept()
                # Increment active connection count
                with self._conn_lock:
                    self.current_connections += 1
                    active_now = self.current_connections
                self.telemetry.update_metrics(active_connections=active_now)

                # Dispatch request handling to a background thread
                threading.Thread(target=self._handle_request, args=(sock, addr), daemon=True).start()
            except Exception:
                if not self.running:
                    break

    def _handle_request(self, sock: socket.socket, addr: tuple) -> None:
        # Process individual client request and measure execution latency
        start_time = time.perf_counter()
        is_error = False
        try:
            sock.settimeout(10.0)
            data = sock.recv(2048)
            if not data:
                return

            # Simulate backend computational work and I/O latency
            delay_sec = max(0.001, (self.processing_delay_ms + random.uniform(-2.0, 2.0)) / 1000.0)
            time.sleep(delay_sec)

            # Determine response status based on injected error rate
            if random.random() < self.error_rate:
                is_error = True
                response_payload = {
                    "server_id": self.server_id,
                    "status": "ERROR_500",
                    "message": "Internal processing failure",
                }
                status_header = "HTTP/1.1 500 Internal Server Error\r\n"
            else:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                response_payload = {
                    "server_id": self.server_id,
                    "status": "SUCCESS",
                    "latency_ms": round(elapsed_ms, 2),
                    "active_conns": self.current_connections,
                }
                status_header = "HTTP/1.1 200 OK\r\n"

            # Construct and send response over raw socket
            body = json.dumps(response_payload)
            response = (
                f"{status_header}"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
                f"{body}"
            )
            sock.sendall(response.encode("utf-8"))

        except Exception as e:
            logger.debug(f"[{self.server_id}] Connection error: {e}")
            is_error = True
        finally:
            # Clean up connection socket
            try:
                sock.close()
            except Exception:
                pass

            # Decrement active connection counter
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            with self._conn_lock:
                self.current_connections = max(0, self.current_connections - 1)
                active_now = self.current_connections

            # Notify telemetry agent of completed request
            self.telemetry.update_metrics(
                active_connections=active_now,
                raw_latency_ms=duration_ms,
                is_error=is_error,
            )


def main():
    # CLI entrypoint for running standalone backend server
    parser = argparse.ArgumentParser(description="SDN Backend TCP Server")
    parser.add_argument("--id", required=True, help="Server ID (e.g. h2, h3, h4)")
    parser.add_argument("--ip", default="0.0.0.0", help="Binding IP address")
    parser.add_argument("--port", type=int, default=8000, help="Service port")
    parser.add_argument("--telemetry-port", type=int, required=True, help="Telemetry port")
    parser.add_argument("--delay", type=float, default=20.0, help="Base processing delay in ms")
    parser.add_argument("--error-rate", type=float, default=0.0, help="Simulated error rate (0.0 to 1.0)")
    args = parser.parse_args()

    server = BackendServer(
        server_id=args.id,
        ip=args.ip,
        service_port=args.port,
        telemetry_port=args.telemetry_port,
        processing_delay_ms=args.delay,
        error_rate=args.error_rate,
    )
    server.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info(f"Stopping Backend {args.id}...")
        server.stop()


if __name__ == "__main__":
    main()
