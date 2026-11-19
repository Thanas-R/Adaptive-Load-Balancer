from __future__ import annotations

import argparse
import logging
import socket
import struct
import threading
from typing import Optional

from controller.adaptive_engine import AdaptiveEngine
from controller.config import load_config
from controller.of13_wire import (
    OFP_VERSION,
    OFPP_CONTROLLER,
    OFPT_ECHO_REPLY,
    OFPT_ECHO_REQUEST,
    OFPT_FEATURES_REPLY,
    OFPT_FEATURES_REQUEST,
    OFPT_HELLO,
    OFPT_PACKET_IN,
    build_flow_mod,
    pack_action_output,
)
from controller.openflow_app import LoadBalancerLogic
from controller.telemetry_collector import TelemetryCollector

logger = logging.getLogger("sdn_controller")


class StandaloneOF13Controller:
    def __init__(self, config_path: str = "config.json"):
        self.config = load_config(config_path)
        network = self.config["network"]
        algorithm = self.config["algorithm"]
        controller = self.config["controller"]

        self.of_host = controller.get("of_host", "0.0.0.0")
        self.of_port = controller.get("of_port", 6653)

        self.engine = AdaptiveEngine(
            weights=algorithm.get("weights"),
            ema_alpha=algorithm.get("ema_alpha", 0.25),
            max_consecutive_failures=algorithm.get("health_check", {}).get("max_consecutive_failures", 3),
            recovery_cooldown_sec=algorithm.get("health_check", {}).get("recovery_cooldown_sec", 5.0),
            degraded_latency_ms=algorithm.get("degraded_latency_ms", 150.0),
            latency_tolerance_ms=algorithm.get("latency_tolerance_ms", 5.0),
            mode=algorithm.get("mode", "adaptive"),
        )

        for backend in self.config["backends"]:
            self.engine.register_backend(
                server_id=backend["id"],
                ip=backend["ip"],
                mac=backend["mac"],
                service_port=backend["service_port"],
                telemetry_port=backend["telemetry_port"],
                switch_port=backend["switch_port"],
                capacity=backend.get("capacity", 100),
                initial_delay_ms=backend.get("initial_delay_ms", 20.0),
                telemetry_ip=backend.get("telemetry_ip"),
            )

        self.lb_logic = LoadBalancerLogic(
            vip=network["vip"],
            vip_mac=network["vip_mac"],
            service_port=network["service_port"],
            engine=self.engine,
            flow_idle_timeout=controller.get("flow_idle_timeout", 30),
            flow_hard_timeout=controller.get("flow_hard_timeout", 300),
        )

        probe_interval = algorithm.get("health_check", {}).get("probe_interval_sec", 1.0)
        self.telemetry = TelemetryCollector(self.engine, probe_interval=probe_interval)

        self.running = False
        self.server_sock: Optional[socket.socket] = None
        self.client_sock: Optional[socket.socket] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self.running:
            return

        self.running = True
        self.telemetry.start()
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_sock.bind((self.of_host, self.of_port))
            self.server_sock.listen(5)
        except OSError:
            self.stop()
            raise

        logger.info("OpenFlow 1.3 controller listening on %s:%s", self.of_host, self.of_port)
        try:
            while self.running:
                client_sock, client_addr = self.server_sock.accept()
                logger.info("Switch connected from %s", client_addr)
                self._handle_switch_connection(client_sock)
        except OSError:
            if self.running:
                logger.exception("Controller socket error")
        finally:
            self.stop()

    def stop(self) -> None:
        self.running = False
        self.telemetry.stop()
        for sock in (self.server_sock, self.client_sock):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        self.server_sock = None
        self.client_sock = None
        logger.info("Controller stopped")

    def _send_msg(self, sock: socket.socket, data: bytes) -> None:
        with self._lock:
            try:
                sock.sendall(data)
            except OSError as exc:
                logger.error("Send failed: %s", exc)

    def _handle_switch_connection(self, sock: socket.socket) -> None:
        self.client_sock = sock
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._send_msg(sock, struct.pack("!BBHI", OFP_VERSION, OFPT_HELLO, 8, 1))

        buffer = bytearray()
        try:
            while self.running:
                chunk = sock.recv(4096)
                if not chunk:
                    logger.warning("Switch disconnected")
                    break

                buffer.extend(chunk)
                while len(buffer) >= 8:
                    version, msg_type, length, xid = struct.unpack("!BBHI", buffer[:8])
                    if length < 8 or len(buffer) < length:
                        break

                    message = bytes(buffer[:length])
                    del buffer[:length]
                    self._process_message(sock, version, msg_type, xid, message)

        except (ConnectionResetError, BrokenPipeError):
            logger.info("Switch connection closed")
        except OSError as exc:
            logger.error("Switch connection error: %s", exc)
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self.client_sock = None

    def _process_message(self, sock: socket.socket, version: int, msg_type: int, xid: int, message: bytes) -> None:
        if version != OFP_VERSION:
            return

        if msg_type == OFPT_HELLO:
            request = struct.pack("!BBHI", OFP_VERSION, OFPT_FEATURES_REQUEST, 8, xid + 1)
            self._send_msg(sock, request)
            return

        if msg_type == OFPT_ECHO_REQUEST:
            self._send_msg(sock, struct.pack("!BBHI", OFP_VERSION, OFPT_ECHO_REPLY, 8, xid))
            return

        if msg_type == OFPT_FEATURES_REPLY:
            if len(message) < 16:
                return
            dpid = struct.unpack("!Q", message[8:16])[0]
            logger.info("Datapath %#018x connected, installing table-miss rule", dpid)
            actions = [pack_action_output(OFPP_CONTROLLER, max_len=0xFFFF)]
            flow = build_flow_mod({}, actions, priority=0, idle_timeout=0, hard_timeout=0, xid=xid + 1)
            self._send_msg(sock, flow)
            return

        if msg_type == OFPT_PACKET_IN:
            self._handle_packet_in(sock, message)

    def _handle_packet_in(self, sock: socket.socket, message: bytes) -> None:
        body = message[8:]
        if len(body) < 16:
            return

        buffer_id, total_len, reason, table_id, cookie = struct.unpack("!IHBBQ", body[:16])
        match_data = body[16:]
        if len(match_data) < 4:
            return

        match_type, match_len = struct.unpack("!HH", match_data[:4])
        if match_len < 4 or len(match_data) < match_len:
            return

        in_port = 1
        offset = 4
        while offset + 4 <= match_len:
            header = struct.unpack("!I", match_data[offset : offset + 4])[0]
            oxm_class = header >> 16
            oxm_field = (header >> 9) & 0x7F
            oxm_len = header & 0xFF
            value = match_data[offset + 4 : offset + 4 + oxm_len]
            if oxm_class == 0x8000 and oxm_field == 0 and len(value) == 4:
                in_port = struct.unpack("!I", value)[0]
            offset += 4 + oxm_len

        padding = (8 - match_len % 8) % 8
        payload_offset = 16 + match_len + padding + 2
        raw_packet = body[payload_offset : payload_offset + total_len]
        if len(raw_packet) < 14:
            return

        flow_mods, packet_out = self.lb_logic.handle_packet_in(in_port, raw_packet)
        for flow_mod in flow_mods:
            self._send_msg(sock, flow_mod)
        if packet_out:
            self._send_msg(sock, packet_out)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Standalone OpenFlow 1.3 SDN controller")
    parser.add_argument("--config", default="config.json", help="path to config.json")
    parser.add_argument("--mode", choices=["adaptive", "round_robin"], help="scheduling mode override")
    args = parser.parse_args()

    controller = StandaloneOF13Controller(args.config)
    if args.mode:
        controller.engine.mode = args.mode

    try:
        controller.start()
    except KeyboardInterrupt:
        controller.stop()


if __name__ == "__main__":
    main()
