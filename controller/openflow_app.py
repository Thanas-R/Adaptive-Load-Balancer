"""OpenFlow 1.3 Load Balancer Logic.

Implements:
1. Virtual IP ARP resolution (intercepts ARP for VIP, emits ARP reply)
2. TCP SYN interception to Virtual IP
3. Server selection via AdaptiveEngine
4. Bi-directional FlowMod installation with NAT address rewriting
5. PacketOut forwarding for initial packet
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from controller.adaptive_engine import AdaptiveEngine, BackendStats
from controller.of13_wire import (
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
        
        # Statistics
        self.total_arp_requests_handled = 0
        self.total_flows_installed = 0
        self.active_sessions: Dict[Tuple[str, int], str] = {}  # (client_ip, client_port) -> server_id

    def handle_packet_in(
        self, in_port: int, raw_data: bytes
    ) -> Tuple[List[bytes], Optional[bytes]]:
        """
        Process an OpenFlow PacketIn message.
        Returns:
            (list_of_flow_mods_to_send, optional_packet_out_to_send)
        """
        flow_mods: List[bytes] = []
        packet_out: Optional[bytes] = None

        eth = parse_ethernet(raw_data)
        if not eth:
            return flow_mods, packet_out

        # Case 1: ARP Request
        if eth.eth_type == ETH_TYPE_ARP:
            arp = parse_arp(eth.payload)
            if arp and arp.opcode == 1:  # ARP Request
                if arp.dst_ip == self.vip:
                    logger.info(
                        f"[ARP] Received request for VIP {self.vip} from {arp.src_ip} ({arp.src_mac}). Sending ARP Reply."
                    )
                    reply_packet = create_arp_reply(
                        sender_mac=self.vip_mac,
                        sender_ip=self.vip,
                        target_mac=arp.src_mac,
                        target_ip=arp.src_ip,
                    )
                    actions = [pack_action_output(in_port)]
                    packet_out = build_packet_out(in_port=0xFFFFFFFD, actions=actions, data=reply_packet)
                    self.total_arp_requests_handled += 1
                    return flow_mods, packet_out

        # Case 2: IPv4 TCP packet destined for VIP:service_port
        if eth.eth_type == ETH_TYPE_IPV4:
            ip = parse_ipv4(eth.payload)
            if ip and ip.protocol == IP_PROTO_TCP and ip.dst_ip == self.vip:
                tcp = parse_tcp(ip.payload)
                if tcp and tcp.dst_port == self.service_port:
                    client_ip = ip.src_ip
                    client_mac = eth.src_mac
                    client_port = tcp.src_port

                    # Select backend using adaptive engine
                    chosen_backend = self.engine.select_backend()
                    if not chosen_backend:
                        logger.error(f"[SDN-LB] Dropping TCP connection from {client_ip}:{client_port}: No healthy backend available!")
                        return flow_mods, packet_out

                    logger.info(
                        f"[SDN-LB] New flow: {client_ip}:{client_port} -> VIP:{self.service_port} => Routed to "
                        f"{chosen_backend.server_id} ({chosen_backend.ip}:{chosen_backend.service_port}) "
                        f"[Latency: {chosen_backend.smoothed_latency_ms:.1f}ms, Conns: {chosen_backend.active_connections}, Score: {chosen_backend.last_score:.3f}]"
                    )

                    self.active_sessions[(client_ip, client_port)] = chosen_backend.server_id

                    # 1. Forward flow rule (Client -> Switch -> Backend)
                    # Rewrite destination MAC to backend MAC, destination IP to backend IP
                    fwd_match = {
                        "in_port": in_port,
                        "eth_type": ETH_TYPE_IPV4,
                        "ip_proto": IP_PROTO_TCP,
                        "ipv4_src": client_ip,
                        "ipv4_dst": self.vip,
                        "tcp_src": client_port,
                        "tcp_dst": self.service_port,
                    }
                    fwd_actions = [
                        pack_action_set_field(OXM_OFB_ETH_DST, mac_to_bytes(chosen_backend.mac)),
                        pack_action_set_field(OXM_OFB_IPV4_DST, ip_to_bytes(chosen_backend.ip)),
                        pack_action_output(chosen_backend.switch_port),
                    ]
                    flow_mods.append(
                        build_flow_mod(
                            match_fields=fwd_match,
                            actions=fwd_actions,
                            priority=100,
                            idle_timeout=self.flow_idle_timeout,
                            hard_timeout=self.flow_hard_timeout,
                        )
                    )

                    # 2. Reverse flow rule (Backend -> Switch -> Client)
                    # Rewrite source MAC to VIP MAC, source IP to VIP
                    rev_match = {
                        "in_port": chosen_backend.switch_port,
                        "eth_type": ETH_TYPE_IPV4,
                        "ip_proto": IP_PROTO_TCP,
                        "ipv4_src": chosen_backend.ip,
                        "ipv4_dst": client_ip,
                        "tcp_src": chosen_backend.service_port,
                        "tcp_dst": client_port,
                    }
                    rev_actions = [
                        pack_action_set_field(OXM_OFB_ETH_SRC, mac_to_bytes(self.vip_mac)),
                        pack_action_set_field(OXM_OFB_IPV4_SRC, ip_to_bytes(self.vip)),
                        pack_action_output(in_port),
                    ]
                    flow_mods.append(
                        build_flow_mod(
                            match_fields=rev_match,
                            actions=rev_actions,
                            priority=100,
                            idle_timeout=self.flow_idle_timeout,
                            hard_timeout=self.flow_hard_timeout,
                        )
                    )

                    self.total_flows_installed += 2

                    # 3. PacketOut: forward the buffered/initial packet to chosen backend
                    # with rewritten MAC and IP
                    fwd_out_actions = [
                        pack_action_set_field(OXM_OFB_ETH_DST, mac_to_bytes(chosen_backend.mac)),
                        pack_action_set_field(OXM_OFB_IPV4_DST, ip_to_bytes(chosen_backend.ip)),
                        pack_action_output(chosen_backend.switch_port),
                    ]
                    packet_out = build_packet_out(
                        in_port=in_port,
                        actions=fwd_out_actions,
                        data=raw_data,
                    )

        return flow_mods, packet_out
