from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Optional

logger = logging.getLogger("telemetry_agent")


class TelemetryAgent:
    def __init__(self, server_id: str, ip: str, port: int):
        self.server_id = server_id
        self.ip = ip
        self.port = port
        self.running = False
        self.server_sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

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
        with self._lock:
            if active_connections is not None:
                self.active_connections = max(0, int(active_connections))

            if raw_latency_ms is not None:
                self.raw_latency_ms = max(0.0, float(raw_latency_ms))
                self.smoothed_latency_ms = 0.25 * self.raw_latency_ms + 0.75 * self.smoothed_latency_ms
                self.total_requests += 1
                if is_error:
                    self.failed_requests += 1

    def get_payload(self) -> dict:
        with self._lock:
            error_rate = self.failed_requests / self.total_requests if self.total_requests else 0.0
            return {
                "server_id": self.server_id,
                "ip": self.ip,
                "status": self.health_status,
                "active_connections": self.active_connections,
                "total_requests": self.total_requests,
                "failed_requests": self.failed_requests,
                "error_rate": round(error_rate, 4),
                "raw_latency_ms": round(self.raw_latency_ms, 2),
                "smoothed_latency_ms": round(self.smoothed_latency_ms, 2),
                "cpu_utilization": round(self.cpu_utilization, 2),
                "uptime_sec": round(time.time() - self.start_time, 1),
            }

    def start(self) -> None:
        if self.running:
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.ip, self.port))
        except OSError:
            if self.port == 0:
                sock.close()
                raise
            sock.bind((self.ip, 0))

        self.port = sock.getsockname()[1]
        sock.listen(10)
        self.server_sock = sock
        self.running = True
        self._thread = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name=f"telemetry-{self.server_id}",
        )
        self._thread.start()
        logger.info("Telemetry agent %s listening on %s:%s", self.server_id, self.ip, self.port)

    def stop(self) -> None:
        self.running = False
        if self.server_sock:
            try:
                self.server_sock.close()
            except OSError:
                pass
            self.server_sock = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _listen_loop(self) -> None:
        while self.running:
            sock = self.server_sock
            if not sock:
                break
            try:
                client_sock, _ = sock.accept()
            except OSError:
                if not self.running:
                    break
                continue
            threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()

    def _handle_client(self, sock: socket.socket) -> None:
        try:
            sock.settimeout(3.0)
            if sock.recv(1024):
                response = json.dumps(self.get_payload()) + "\n"
                sock.sendall(response.encode("utf-8"))
        except OSError as exc:
            logger.debug("Telemetry handler error: %s", exc)
        finally:
            try:
                sock.close()
            except OSError:
                pass
