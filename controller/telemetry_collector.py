"""Telemetry Collector for the SDN Controller.

Periodically queries backend telemetry agents via TCP sockets or accepts
push telemetry updates, feeding metrics directly into the AdaptiveEngine.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Dict, List, Optional

from controller.adaptive_engine import AdaptiveEngine

logger = logging.getLogger("telemetry_collector")


class TelemetryCollector:
    def __init__(
        self,
        engine: AdaptiveEngine,
        probe_interval: float = 1.0,
        timeout: float = 2.0,
    ):
        # Reference to shared adaptive engine and probe timing
        self.engine = engine
        self.probe_interval = probe_interval
        self.timeout = timeout
        self.running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        # Start background polling thread
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="TelemetryCollector")
        self._thread.start()
        logger.info(f"Telemetry collector started with {self.probe_interval}s probe interval.")

    def stop(self) -> None:
        # Gracefully terminate collector thread
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Telemetry collector stopped.")

    def _poll_loop(self) -> None:
        # Continually query each registered backend server on its telemetry port
        while self.running:
            backend_keys = list(self.engine.backends.keys())
            for sid in backend_keys:
                if not self.running:
                    break
                backend = self.engine.backends.get(sid)
                if not backend:
                    continue
                self.poll_backend(backend.server_id, backend.ip, backend.telemetry_port)
            time.sleep(self.probe_interval)

    def poll_backend(self, server_id: str, ip: str, port: int) -> Optional[dict]:
        # Connect to backend telemetry socket, send STATS command, and update engine
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((ip, port))
            sock.sendall(b"STATS\n")

            # Read newline-terminated JSON response
            buffer = bytearray()
            while True:
                chunk = sock.recv(2048)
                if not chunk:
                    break
                buffer.extend(chunk)
                if b"\n" in chunk:
                    break

            if buffer:
                data_str = buffer.decode("utf-8").strip()
                payload = json.loads(data_str)
                self.engine.update_telemetry(server_id, payload)
                return payload
            else:
                self.engine.record_probe_failure(server_id)
                return None

        except (socket.timeout, socket.error, ConnectionRefusedError, OSError) as e:
            # Server unreachable or dead
            logger.debug(f"Health probe to {server_id} ({ip}:{port}) failed: {e}")
            self.engine.record_probe_failure(server_id)
            return None
        except Exception as e:
            logger.warning(f"Unexpected error polling {server_id}: {e}")
            self.engine.record_probe_failure(server_id)
            return None
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
