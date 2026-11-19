from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from controller.adaptive_engine import AdaptiveEngine
from controller.of13_wire import (
    OFPP_CONTROLLER,
    OXM_OFB_ETH_DST,
    OXM_OFB_ETH_SRC,
    OXM_OFB_IPV4_DST,
    OXM_OFB_IPV4_SRC,
    build_flow_mod,
    build_packet_out,
    ip_to_bytes,
    mac_to_bytes,
    pack_action_output,
    pack_action_set_field,
)
from controller.packet_utils import (
    ARP_OP_REQUEST,
    ETH_TYPE_ARP,
    ETH_TYPE_IPV4,
    IP_PROTO_TCP,
    create_arp_reply,
    parse_arp,
    parse_ethernet,
    parse_ipv4,
    parse_tcp,
)

logger = logging.getLogger("openflow_lb")


class LoadBalancerLogic:
    def __init__(
        self,
        vip: str,
        vip_mac: str,
        service_port: int,
        engine: AdaptiveEngine,
        flow_idle_timeout: int = 30,
        flow_hard_timeout: int = 300,
    ):
        self.vip = vip
        self.vip_mac = vip_mac.lower()
        self.service_port = service_port
        self.engine = engine
        self.flow_idle_timeout = flow_idle_timeout
        self.flow_hard_timeout = flow_hard_timeout

        self.total_arp_requests_handled = 0
        self.total_flows_installed = 0
        self.active_sessions: Dict[Tuple[str, int], str] = {}

    def handle_packet_in(self, in_port: int, raw_data: bytes) -> Tuple[List[bytes], Optional[bytes]]:
        flow_mods: List[bytes] = []
        packet_out: Optional[bytes] = None

        ethernet = parse_ethernet(raw_data)
        if not ethernet:
            return flow_mods, packet_out

        if ethernet.eth_type == ETH_TYPE_ARP:
            arp = parse_arp(ethernet.payload)
            if arp and arp.opcode == ARP_OP_REQUEST and arp.dst_ip == self.vip:
                reply = create_arp_reply(
                    sender_mac=self.vip_mac,
                    sender_ip=self.vip,
                    target_mac=arp.src_mac,
                    target_ip=arp.src_ip,
                )
                actions = [pack_action_output(in_port)]
                packet_out = build_packet_out(OFPP_CONTROLLER, actions, reply)
                self.total_arp_requests_handled += 1
            return flow_mods, packet_out

        if ethernet.eth_type != ETH_TYPE_IPV4:
            return flow_mods, packet_out

        ipv4 = parse_ipv4(ethernet.payload)
        if not ipv4 or ipv4.protocol != IP_PROTO_TCP or ipv4.dst_ip != self.vip:
            return flow_mods, packet_out

        tcp = parse_tcp(ipv4.payload)
        if not tcp or tcp.dst_port != self.service_port:
            return flow_mods, packet_out

        backend = self.engine.select_backend()
        if not backend:
            logger.error("Dropping flow from %s:%s, no backend available", ipv4.src_ip, tcp.src_port)
            return flow_mods, packet_out

        logger.info(
            "Flow %s:%s -> %s, backend %s (%s), score %.3f",
            ipv4.src_ip,
            tcp.src_port,
            self.vip,
            backend.server_id,
            backend.ip,
            backend.last_score,
        )
        self.active_sessions[(ipv4.src_ip, tcp.src_port)] = backend.server_id

        # Forward path: client to backend
        forward_match = {
            "in_port": in_port,
            "eth_type": ETH_TYPE_IPV4,
            "ip_proto": IP_PROTO_TCP,
            "ipv4_src": ipv4.src_ip,
            "ipv4_dst": self.vip,
            "tcp_src": tcp.src_port,
            "tcp_dst": self.service_port,
        }
        forward_actions = [
            pack_action_set_field(OXM_OFB_ETH_DST, mac_to_bytes(backend.mac)),
            pack_action_set_field(OXM_OFB_IPV4_DST, ip_to_bytes(backend.ip)),
            pack_action_output(backend.switch_port),
        ]
        flow_mods.append(
            build_flow_mod(
                forward_match,
                forward_actions,
                priority=100,
                idle_timeout=self.flow_idle_timeout,
                hard_timeout=self.flow_hard_timeout,
            )
        )

        # Reverse path: backend to client
        reverse_match = {
            "in_port": backend.switch_port,
            "eth_type": ETH_TYPE_IPV4,
            "ip_proto": IP_PROTO_TCP,
            "ipv4_src": backend.ip,
            "ipv4_dst": ipv4.src_ip,
            "tcp_src": backend.service_port,
            "tcp_dst": tcp.src_port,
        }
        reverse_actions = [
            pack_action_set_field(OXM_OFB_ETH_SRC, mac_to_bytes(self.vip_mac)),
            pack_action_set_field(OXM_OFB_IPV4_SRC, ip_to_bytes(self.vip)),
            pack_action_output(in_port),
        ]
        flow_mods.append(
            build_flow_mod(
                reverse_match,
                reverse_actions,
                priority=100,
                idle_timeout=self.flow_idle_timeout,
                hard_timeout=self.flow_hard_timeout,
            )
        )

        self.total_flows_installed += 2
        packet_out = build_packet_out(in_port, forward_actions, raw_data)
        return flow_mods, packet_out
