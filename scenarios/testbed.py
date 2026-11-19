from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Dict, Optional, Tuple

from backend.server import BackendServer
from client.client import TcpClient
from controller.adaptive_engine import AdaptiveEngine, BackendStats
from controller.telemetry_collector import TelemetryCollector

logger = logging.getLogger("sdn_testbed")


class SDNTestbed:
    def __init__(self, vip: str = "127.0.0.1", vip_port: int = 8000, mode: str = "adaptive"):
        self.vip = vip
        self.vip_port = vip_port
        self.mode = mode
        self.engine = AdaptiveEngine(
            weights={"active_connections": 0.50, "smoothed_latency": 0.35, "error_rate": 0.15},
            ema_alpha=0.25,
            max_consecutive_failures=3,
            recovery_cooldown_sec=3.0,
            mode=mode,
        )
        self.telemetry = TelemetryCollector(self.engine, probe_interval=0.5, timeout=1.0)
        self.servers: Dict[str, BackendServer] = {}
        self._server_configs = [
            {"id": "h2", "ip": "127.0.0.1", "port": 8002, "telemetry_port": 9002, "switch_port": 2, "delay": 20.0},
            {"id": "h3", "ip": "127.0.0.1", "port": 8003, "telemetry_port": 9003, "switch_port": 3, "delay": 20.0},
            {"id": "h4", "ip": "127.0.0.1", "port": 8004, "telemetry_port": 9004, "switch_port": 4, "delay": 20.0},
        ]

        self.running = False
        self.switch_sock: Optional[socket.socket] = None
        self._switch_thread: Optional[threading.Thread] = None
        self._flow_lock = threading.Lock()
        self.total_flows_routed = 0

    def start(self) -> None:
        if self.running:
            return

        logger.info("Starting SDN testbed")
        started: list[BackendServer] = []
        try:
            for cfg in self._server_configs:
                server = BackendServer(
                    server_id=cfg["id"],
                    ip=cfg["ip"],
                    service_port=cfg["port"],
                    telemetry_port=cfg["telemetry_port"],
                    processing_delay_ms=cfg["delay"],
                )
                server.start()
                started.append(server)
                self.servers[cfg["id"]] = server
                self.engine.register_backend(
                    server_id=cfg["id"],
                    ip=server.ip,
                    mac=f"00:00:00:00:00:0{cfg['switch_port']}",
                    service_port=server.service_port,
                    telemetry_port=server.telemetry_port,
                    switch_port=cfg["switch_port"],
                    initial_delay_ms=cfg["delay"],
                    telemetry_ip=server.telemetry_ip,
                )

            self.telemetry.start()
            self.running = True
            self._start_switch()
            time.sleep(1.0)
        except Exception:
            self.running = False
            for server in started:
                server.stop()
            self.telemetry.stop()
            self._close_switch()
            self.servers.clear()
            raise

    def _start_switch(self) -> None:
        self.switch_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.switch_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.switch_sock.bind((self.vip, self.vip_port))
        except OSError:
            if self.vip_port == 0:
                self.switch_sock.close()
                self.switch_sock = None
                raise
            self.switch_sock.bind((self.vip, 0))

        self.vip_port = self.switch_sock.getsockname()[1]
        self.switch_sock.listen(128)
        self._switch_thread = threading.Thread(target=self._switch_loop, daemon=True, name="sdn-datapath")
        self._switch_thread.start()
        logger.info("SDN datapath listening on %s:%s", self.vip, self.vip_port)

    def _close_switch(self) -> None:
        if self.switch_sock:
            try:
                self.switch_sock.close()
            except OSError:
                pass
            self.switch_sock = None

    def stop(self) -> None:
        if not self.running:
            return

        self.running = False
        self.telemetry.stop()
        self._close_switch()
        if self._switch_thread and self._switch_thread.is_alive():
            self._switch_thread.join(timeout=1.0)
        self._switch_thread = None
        for server in self.servers.values():
            server.stop()
        self.servers.clear()
        logger.info("SDN testbed stopped")

    def poll_backend(self, server_id: str) -> Optional[dict]:
        server = self.servers.get(server_id)
        if not server:
            return None
        host = server.telemetry_ip or server.ip
        return self.telemetry.poll_backend(server_id, host, server.telemetry_port)

    def refresh_telemetry(self) -> None:
        for server_id, server in list(self.servers.items()):
            host = server.telemetry_ip or server.ip
            self.telemetry.poll_backend(server_id, host, server.telemetry_port)

    def warm_backend(self, server_id: str, count: int = 5) -> int:
        server = self.servers.get(server_id)
        if not server:
            return 0

        timeout = max(2.0, server.processing_delay_ms / 1000.0 + 1.0)
        client = TcpClient(server.ip, server.service_port, timeout=timeout)
        successes = 0
        for _ in range(count):
            success, _, _, _ = client.send_request({"warmup": True})
            if success:
                successes += 1
        return successes

    def restart_backend(self, server_id: str, delay_ms: float = 20.0) -> Optional[BackendServer]:
        old = self.servers.get(server_id)
        if not old:
            return None

        old.stop()
        server = BackendServer(
            server_id=server_id,
            ip=old.ip,
            service_port=old.service_port,
            telemetry_port=old.telemetry_port,
            telemetry_ip=old.telemetry_ip,
            processing_delay_ms=delay_ms,
        )
        server.start()
        self.servers[server_id] = server

        backend = self.engine.backends.get(server_id)
        if backend:
            backend.ip = server.ip
            backend.service_port = server.service_port
            backend.telemetry_port = server.telemetry_port
            backend.telemetry_ip = server.telemetry_ip
        return server

    def _switch_loop(self) -> None:
        while self.running:
            sock = self.switch_sock
            if not sock:
                break
            try:
                client_sock, client_addr = sock.accept()
            except OSError:
                if not self.running:
                    break
                continue
            threading.Thread(
                target=self._route_flow,
                args=(client_sock, client_addr),
                daemon=True,
            ).start()

    def _connect_backend(self) -> Tuple[Optional[BackendStats], Optional[socket.socket]]:
        skipped: set[str] = set()

        for _ in range(3):
            backend = self.engine.select_backend(exclude=skipped)
            if not backend:
                return None, None

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            try:
                sock.connect((backend.ip, backend.service_port))
                return backend, sock
            except OSError:
                sock.close()
                skipped.add(backend.server_id)
                self.engine.release_backend(backend.server_id)
                self.engine.record_probe_failure(backend.server_id)

        return None, None

    def _route_flow(self, client_sock: socket.socket, client_addr: tuple) -> None:
        backend, backend_sock = self._connect_backend()
        if not backend or not backend_sock:
            logger.error("Dropping flow from %s, no reachable backend", client_addr)
            try:
                client_sock.close()
            except OSError:
                pass
            return

        with self._flow_lock:
            self.total_flows_routed += 1

        try:
            def forward(src: socket.socket, dst: socket.socket) -> None:
                try:
                    while True:
                        chunk = src.recv(4096)
                        if not chunk:
                            break
                        dst.sendall(chunk)
                except OSError:
                    pass
                finally:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass

            upstream = threading.Thread(target=forward, args=(client_sock, backend_sock), daemon=True)
            downstream = threading.Thread(target=forward, args=(backend_sock, client_sock), daemon=True)
            upstream.start()
            downstream.start()
            upstream.join(timeout=10.0)
            downstream.join(timeout=10.0)

        except OSError as exc:
            logger.debug("Flow routing error: %s", exc)
        finally:
            self.engine.release_backend(backend.server_id)
            try:
                backend_sock.close()
            except OSError:
                pass
            try:
                client_sock.close()
            except OSError:
                pass
