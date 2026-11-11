"""Standalone Native OpenFlow 1.3 SDN Controller.

Implements full OpenFlow 1.3 protocol handshake and event loop:
- OFPT_HELLO
- OFPT_FEATURES_REQUEST / OFPT_FEATURES_REPLY
- Table-miss FlowMod installation (matches all, sends to controller)
- Echo Request / Echo Reply keepalives
- OFPT_PACKET_IN handling for ARP and TCP load balancing
- Thread-safe socket management
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import struct
import threading
import time
from typing import Optional

from controller.adaptive_engine import AdaptiveEngine
from controller.of13_wire import (
    OFP_VERSION,
    OFPP_CONTROLLER,
    OFPT_ECHO_REPLY,
    OFPT_ECHO_REQUEST,
    OFPT_FEATURES_REPLY,
    OFPT_FEATURES_REQUEST,
    OFPT_FLOW_MOD,
    OFPT_HELLO,
    OFPT_PACKET_IN,
    OFPT_PACKET_OUT,
    build_flow_mod,
    pack_action_output,
)
from controller.openflow_app import LoadBalancerLogic
from controller.telemetry_collector import TelemetryCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sdn_controller")


class StandaloneOF13Controller:
    def __init__(self, config_path: str = "config.json"):
        with open(config_path, "r") as f:
            self.config = json.load(f)

        net_cfg = self.config["network"]
        alg_cfg = self.config["algorithm"]
        ctrl_cfg = self.config["controller"]

        self.of_host = ctrl_cfg.get("of_host", "0.0.0.0")
        self.of_port = ctrl_cfg.get("of_port", 6653)

        # Initialize Adaptive Engine
        self.engine = AdaptiveEngine(
            weights=alg_cfg.get("weights"),
            ema_alpha=alg_cfg.get("ema_alpha", 0.25),
            max_consecutive_failures=alg_cfg.get("health_check", {}).get("max_consecutive_failures", 3),
            recovery_cooldown_sec=alg_cfg.get("health_check", {}).get("recovery_cooldown_sec", 5.0),
            mode=alg_cfg.get("mode", "adaptive"),
        )

        # Register backends from configuration
        for b in self.config["backends"]:
            self.engine.register_backend(
                server_id=b["id"],
                ip=b["ip"],
                mac=b["mac"],
                service_port=b["service_port"],
                telemetry_port=b["telemetry_port"],
                switch_port=b["switch_port"],
                capacity=b.get("capacity", 100),
                initial_delay_ms=b.get("initial_delay_ms", 20.0),
            )

        # Initialize Load Balancer Logic
        self.lb_logic = LoadBalancerLogic(
            vip=net_cfg["vip"],
            vip_mac=net_cfg["vip_mac"],
            service_port=net_cfg["service_port"],
            engine=self.engine,
            flow_idle_timeout=ctrl_cfg.get("flow_idle_timeout", 30),
            flow_hard_timeout=ctrl_cfg.get("flow_hard_timeout", 300),
        )

        # Initialize Telemetry Collector
        probe_interval = alg_cfg.get("health_check", {}).get("probe_interval_sec", 1.0)
        self.telemetry = TelemetryCollector(self.engine, probe_interval=probe_interval)

        self.running = False
        self.server_sock: Optional[socket.socket] = None
        self.client_sock: Optional[socket.socket] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self.running = True
        self.telemetry.start()

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.of_host, self.of_port))
        self.server_sock.listen(5)
        logger.info(f"OpenFlow 1.3 Controller listening on {self.of_host}:{self.of_port}")

        try:
            while self.running:
                client_sock, client_addr = self.server_sock.accept()
                logger.info(f"Switch connected from {client_addr}")
                self._handle_switch_connection(client_sock)
        except Exception as e:
            if self.running:
                logger.error(f"Controller server error: {e}")
        finally:
            self.stop()

    def stop(self) -> None:
        self.running = False
        self.telemetry.stop()
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
        if self.client_sock:
            try:
                self.client_sock.close()
            except Exception:
                pass
        logger.info("Controller shut down.")

    def _send_msg(self, sock: socket.socket, data: bytes) -> None:
        with self._lock:
            try:
                sock.sendall(data)
            except Exception as e:
                logger.error(f"Error sending message to switch: {e}")

    def _handle_switch_connection(self, sock: socket.socket) -> None:
        self.client_sock = sock
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        # 1. Send OFPT_HELLO to switch
        hello_msg = struct.pack("!BBHI", OFP_VERSION, OFPT_HELLO, 8, 1)
        self._send_msg(sock, hello_msg)

        buffer = bytearray()
        try:
            while self.running:
                chunk = sock.recv(4096)
                if not chunk:
                    logger.warning("Switch disconnected.")
                    break
                buffer.extend(chunk)

                # Process all complete OpenFlow messages in buffer
                while len(buffer) >= 8:
                    version, msg_type, length, xid = struct.unpack("!BBHI", buffer[:8])
                    if len(buffer) < length:
                        # Partial message, wait for more bytes
                        break

                    msg_data = bytes(buffer[:length])
                    del buffer[:length]

                    self._process_of_message(sock, version, msg_type, length, xid, msg_data)

        except (ConnectionResetError, BrokenPipeError):
            logger.info("Switch connection closed.")
        except Exception as e:
            logger.error(f"Switch handling exception: {e}")
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _process_of_message(
        self,
        sock: socket.socket,
        version: int,
        msg_type: int,
        length: int,
        xid: int,
        msg_data: bytes,
    ) -> None:
        if msg_type == OFPT_HELLO:
            logger.info("Received OFPT_HELLO from switch. Sending OFPT_FEATURES_REQUEST.")
            # Send OFPT_FEATURES_REQUEST
            feat_req = struct.pack("!BBHI", OFP_VERSION, OFPT_FEATURES_REQUEST, 8, xid + 1)
            self._send_msg(sock, feat_req)

        elif msg_type == OFPT_ECHO_REQUEST:
            # Reply with OFPT_ECHO_REPLY
            echo_reply = struct.pack("!BBHI", OFP_VERSION, OFPT_ECHO_REPLY, 8, xid)
            self._send_msg(sock, echo_reply)

        elif msg_type == OFPT_FEATURES_REPLY:
            # Switch features received (DPID, tables, etc.)
            dpid_bytes = msg_data[8:16]
            dpid = struct.unpack("!Q", dpid_bytes)[0]
            logger.info(f"Switch Handshake Complete! Datapath ID: {dpid:#018x}. Installing Table-Miss rule...")
            
            # Install Table-Miss Flow: Priority 0, match everything, action: Output to Controller
            actions = [pack_action_output(OFPP_CONTROLLER, max_len=0xFFFF)]
            table_miss_flow = build_flow_mod(
                match_fields={},  # Wildcard match (all packets)
                actions=actions,
                priority=0,
                idle_timeout=0,
                hard_timeout=0,
                xid=xid + 1,
            )
            self._send_msg(sock, table_miss_flow)
            logger.info("Table-miss rule installed successfully. SDN Controller is now actively routing flows.")

        elif msg_type == OFPT_PACKET_IN:
            # Parse OFPT_PACKET_IN
            # Header is 8 bytes.
            # Body: buffer_id (4B), total_len (2B), reason (1B), table_id (1B), cookie (8B)
            # Match structure: type (2B), length (2B), oxm_fields, padding to 8 bytes
            # Pad 2 bytes before payload
            if len(msg_data) < 24:
                return

            body = msg_data[8:]
            buffer_id, total_len, reason, table_id, cookie = struct.unpack("!IHBBQ", body[:16])
            
            # Parse match to extract in_port
            match_data = body[16:]
            match_type, match_len = struct.unpack("!HH", match_data[:4])
            
            in_port = 1
            oxm_offset = 4
            oxm_end = match_len
            while oxm_offset + 4 <= oxm_end:
                oxm_hdr = struct.unpack("!I", match_data[oxm_offset : oxm_offset + 4])[0]
                oxm_class = oxm_hdr >> 16
                oxm_field = (oxm_hdr >> 9) & 0x7F
                oxm_len = oxm_hdr & 0xFF
                val = match_data[oxm_offset + 4 : oxm_offset + 4 + oxm_len]
                if oxm_class == 0x8000 and oxm_field == 0:  # IN_PORT
                    in_port = struct.unpack("!I", val)[0]
                oxm_offset += 4 + oxm_len

            # Calculate start of raw Ethernet packet payload
            # Pad match to 8-byte boundary, then 2 bytes pad
            pad_len = (8 - (match_len % 8)) % 8
            payload_offset = 16 + match_len + pad_len + 2
            raw_packet = body[payload_offset : payload_offset + total_len]

            # Pass to LoadBalancerLogic
            flow_mods, packet_out = self.lb_logic.handle_packet_in(in_port, raw_packet)

            # Send FlowMods if any
            for fm in flow_mods:
                self._send_msg(sock, fm)

            # Send PacketOut if any
            if packet_out:
                self._send_msg(sock, packet_out)


def main():
    parser = argparse.ArgumentParser(description="Standalone OpenFlow 1.3 SDN Controller")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--mode", choices=["adaptive", "round_robin"], help="Override load balancing mode")
    args = parser.parse_args()

    controller = StandaloneOF13Controller(args.config)
    if args.mode:
        controller.engine.mode = args.mode
        logger.info(f"Loaded with scheduling mode override: {args.mode}")

    try:
        controller.start()
    except KeyboardInterrupt:
        logger.info("Terminating SDN Controller...")
        controller.stop()


if __name__ == "__main__":
    main()
