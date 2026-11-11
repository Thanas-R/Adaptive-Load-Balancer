"""TCP Telemetry Agent for Backend Servers.

Exposes server metrics to the SDN controller over a dedicated TCP socket.
Metrics include:
- Active TCP connections
- Smoothed response latency (EMA)
- Error rate and total or failed request counts
- Health status and simulated CPU utilization
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Optional

logger = logging.getLogger("telemetry_agent")


class TelemetryAgent:
    def __init__(
        self,
        server_id: str,
        ip: str,
        port: int,
    ):
        # Identity and telemetry socket port
        self.server_id = server_id
        self.ip = ip
        self.port = port
        self.running = False
        self.server_sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

        # State tracked from backend server
        self.active_connections = 0
        self.total_requests = 0
        self.failed_requests = 0
        self.raw_latency_ms = 20.0
        self.smoothed_latency_ms = 20.0
        self.cpu_utilization = 0.15
        self.health_status = "HEALTHY"
        self.start_time = time.time()
        self._lock = threading.Lock()

    def update_metrics(
        self,
        active_connections: Optional[int] = None,
        raw_latency_ms: Optional[float] = None,
        is_error: bool = False,
    ) -> None:
        # Update server metrics atomically
        with self._lock:
            if active_connections is not None:
                self.active_connections = max(0, active_connections)
            if raw_latency_ms is not None:
                self.raw_latency_ms = raw_latency_ms
                # Exponential Moving Average: 25% current sample, 75% historical weight
                self.smoothed_latency_ms = 0.25 * raw_latency_ms + 0.75 * self.smoothed_latency_ms
                self.total_requests += 1
                if is_error:
                    self.failed_requests += 1

    def get_payload(self) -> dict:
        # Generate JSON telemetry snapshot dictionary
        with self._lock:
            err_rate = (
                self.failed_requests / float(self.total_requests)
                if self.total_requests > 0
                else 0.0
            )
            return {
                "server_id": self.server_id,
                "ip": self.ip,
                "status": self.health_status,
                "active_connections": self.active_connections,
                "total_requests": self.total_requests,
                "failed_requests": self.failed_requests,
                "error_rate": round(err_rate, 4),
                "raw_latency_ms": round(self.raw_latency_ms, 2),
                "smoothed_latency_ms": round(self.smoothed_latency_ms, 2),
                "cpu_utilization": round(self.cpu_utilization, 2),
                "uptime_sec": round(time.time() - self.start_time, 1),
            }

    def start(self) -> None:
        # Initialize and bind telemetry TCP socket
        self.running = True
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.ip, self.port))
        self.server_sock.listen(10)

        # Start telemetry listening thread
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name=f"TelemetryAgent-{self.server_id}")
        self._thread.start()
        logger.info(f"Telemetry Agent for {self.server_id} listening on {self.ip}:{self.port}")

    def stop(self) -> None:
        # Terminate telemetry listening thread and close socket
        self.running = False
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info(f"Telemetry Agent for {self.server_id} stopped.")

    def _listen_loop(self) -> None:
        # Accept telemetry probe connections from SDN controller
        while self.running:
            try:
                client_sock, _ = self.server_sock.accept()
                threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()
            except Exception:
                if not self.running:
                    break

    def _handle_client(self, sock: socket.socket) -> None:
        # Respond to STATS query with JSON payload
        try:
            sock.settimeout(3.0)
            data = sock.recv(1024)
            if data:
                payload = self.get_payload()
                response = json.dumps(payload) + "\n"
                sock.sendall(response.encode("utf-8"))
        except Exception as e:
            logger.debug(f"Telemetry handler error: {e}")
        finally:
            try:
                sock.close()
            except Exception:
                pass
