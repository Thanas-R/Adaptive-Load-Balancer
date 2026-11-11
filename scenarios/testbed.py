"""Emulated SDN Testbed for Demonstration Scenarios and Verification.

Provides an in-process SDN forwarding datapath and multi-threaded TCP backends
to execute the complete scenario test suite on any platform (or Mininet).
Runs the actual AdaptiveEngine, TelemetryCollector, and BackendServer code.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Dict, Optional

from backend.server import BackendServer
from controller.adaptive_engine import AdaptiveEngine
from controller.telemetry_collector import TelemetryCollector

logger = logging.getLogger("sdn_testbed")


class SDNTestbed:
    def __init__(
        self,
        vip: str = "127.0.0.1",
        vip_port: int = 8000,
        mode: str = "adaptive",
    ):
        self.vip = vip
        self.vip_port = vip_port
        self.mode = mode

        # Initialize Adaptive Engine
        self.engine = AdaptiveEngine(
            weights={"active_connections": 0.50, "smoothed_latency": 0.35, "error_rate": 0.15},
            ema_alpha=0.25,
            max_consecutive_failures=3,
            recovery_cooldown_sec=3.0,
            mode=mode,
        )

        # Telemetry Collector
        self.telemetry = TelemetryCollector(self.engine, probe_interval=0.5, timeout=1.0)

        # Backends
        self.servers: Dict[str, BackendServer] = {}
        self._server_configs = [
            {"id": "h2", "ip": "127.0.0.1", "port": 8002, "telemetry_port": 9002, "switch_port": 2, "delay": 20.0},
            {"id": "h3", "ip": "127.0.0.1", "port": 8003, "telemetry_port": 9003, "switch_port": 3, "delay": 20.0},
            {"id": "h4", "ip": "127.0.0.1", "port": 8004, "telemetry_port": 9004, "switch_port": 4, "delay": 20.0},
        ]

        # Datapath switch proxy listening on VIP:vip_port
        self.running = False
        self.switch_sock: Optional[socket.socket] = None
        self._switch_thread: Optional[threading.Thread] = None
        self.total_flows_routed = 0

    def start(self) -> None:
        self.running = True
        logger.info("Starting SDN Testbed...")

        # Start backends
        for cfg in self._server_configs:
            server = BackendServer(
                server_id=cfg["id"],
                ip=cfg["ip"],
                service_port=cfg["port"],
                telemetry_port=cfg["telemetry_port"],
                processing_delay_ms=cfg["delay"],
            )
            server.start()
            self.servers[cfg["id"]] = server

            self.engine.register_backend(
                server_id=cfg["id"],
                ip=cfg["ip"],
                mac=f"00:00:00:00:00:0{cfg['switch_port']}",
                service_port=cfg["port"],
                telemetry_port=cfg["telemetry_port"],
                switch_port=cfg["switch_port"],
                initial_delay_ms=cfg["delay"],
            )

        # Start Telemetry Collector
        self.telemetry.start()

        # Start Switch Datapath on VIP
        self.switch_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.switch_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.switch_sock.bind((self.vip, self.vip_port))
        self.switch_sock.listen(128)

        self._switch_thread = threading.Thread(target=self._switch_loop, daemon=True, name="SDNSwitchDatapath")
        self._switch_thread.start()
        logger.info(f"SDN Switch Datapath listening on {self.vip}:{self.vip_port}")
        time.sleep(1.0)  # Allow telemetry initial discovery

    def stop(self) -> None:
        self.running = False
        self.telemetry.stop()
        if self.switch_sock:
            try:
                self.switch_sock.close()
            except Exception:
                pass
        for s in self.servers.values():
            s.stop()
        logger.info("SDN Testbed stopped.")

    def _switch_loop(self) -> None:
        while self.running:
            try:
                client_sock, client_addr = self.switch_sock.accept()
                threading.Thread(target=self._route_flow, args=(client_sock, client_addr), daemon=True).start()
            except Exception:
                if not self.running:
                    break

    def _route_flow(self, client_sock: socket.socket, client_addr: tuple) -> None:
        """
        Emulates OpenFlow 1.3 flow matching and NAT forwarding:
        1. Selects backend server using SDN controller engine
        2. Rewrites destination to backend IP:port
        3. Bi-directionally proxies data (emulating OpenFlow pipeline forwarding)
        """
        backend = self.engine.select_backend()
        if not backend:
            logger.error("SDN Switch: Dropping flow, no healthy backend available!")
            try:
                client_sock.close()
            except Exception:
                pass
            return

        self.total_flows_routed += 1
        backend_sock = None
        try:
            backend_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            backend_sock.settimeout(5.0)
            backend_sock.connect((backend.ip, backend.service_port))

            # Bi-directional stream forwarding
            def forward(src, dst):
                try:
                    while True:
                        buf = src.recv(4096)
                        if not buf:
                            break
                        dst.sendall(buf)
                except Exception:
                    pass
                finally:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass

            t1 = threading.Thread(target=forward, args=(client_sock, backend_sock), daemon=True)
            t2 = threading.Thread(target=forward, args=(backend_sock, client_sock), daemon=True)
            t1.start()
            t2.start()
            t1.join(timeout=10.0)
            t2.join(timeout=10.0)

        except Exception as e:
            logger.debug(f"Flow routing error: {e}")
        finally:
            if backend_sock:
                try:
                    backend_sock.close()
                except Exception:
                    pass
            try:
                client_sock.close()
            except Exception:
                pass
