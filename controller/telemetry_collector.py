from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Optional

from controller.adaptive_engine import AdaptiveEngine

logger = logging.getLogger("telemetry_collector")


class TelemetryCollector:
    def __init__(self, engine: AdaptiveEngine, probe_interval: float = 1.0, timeout: float = 2.0):
        self.engine = engine
        self.probe_interval = max(0.05, float(probe_interval))
        self.timeout = max(0.1, float(timeout))
        self.running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="telemetry-collector")
        self._thread.start()
        logger.info("Telemetry collector started, interval %.2f s", self.probe_interval)

    def stop(self) -> None:
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _poll_loop(self) -> None:
        while self.running:
            for server_id in list(self.engine.backends.keys()):
                if not self.running:
                    break
                backend = self.engine.backends.get(server_id)
                if backend:
                    host = backend.telemetry_ip or backend.ip
                    self.poll_backend(server_id, host, backend.telemetry_port)
            time.sleep(self.probe_interval)

    def poll_backend(self, server_id: str, ip: str, port: int) -> Optional[dict]:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((ip, port))
            sock.sendall(b"STATS\n")

            buffer = bytearray()
            while True:
                chunk = sock.recv(2048)
                if not chunk:
                    break
                buffer.extend(chunk)
                if b"\n" in chunk:
                    break

            if not buffer:
                self.engine.record_probe_failure(server_id)
                return None

            payload = json.loads(buffer.decode("utf-8").strip())
            self.engine.update_telemetry(server_id, payload)
            return payload

        except (socket.timeout, socket.error, OSError, ValueError, json.JSONDecodeError) as exc:
            logger.debug("Probe failed for %s at %s:%s: %s", server_id, ip, port, exc)
            self.engine.record_probe_failure(server_id)
            return None
        finally:
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
