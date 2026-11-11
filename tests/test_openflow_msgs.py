"""Unit tests for OpenFlow 1.3 wire protocol framing and LoadBalancerLogic."""

import struct
import pytest
from controller.adaptive_engine import AdaptiveEngine
from controller.of13_wire import (
    OFP_VERSION,
    OFPT_FLOW_MOD,
    OFPT_HELLO,
    OFPT_PACKET_OUT,
    OXM_OFB_ETH_DST,
    OXM_OFB_IPV4_DST,
    build_flow_mod,
    build_packet_out,
    ip_to_bytes,
    mac_to_bytes,
    pack_action_output,
    pack_action_set_field,
)
from controller.openflow_app import LoadBalancerLogic
from controller.packet_utils import (
    create_arp_reply,
    parse_arp,
    parse_ethernet,
    parse_ipv4,
    parse_tcp,
)


def test_of13_flow_mod_builder():
    match = {
        "in_port": 1,
        "eth_type": 0x0800,
        "ip_proto": 6,
        "ipv4_src": "10.0.0.1",
        "ipv4_dst": "10.0.0.100",
        "tcp_src": 45000,
        "tcp_dst": 8000,
    }
    actions = [
        pack_action_set_field(OXM_OFB_ETH_DST, mac_to_bytes("00:00:00:00:00:02")),
        pack_action_set_field(OXM_OFB_IPV4_DST, ip_to_bytes("10.0.0.2")),
        pack_action_output(2),
    ]
    raw_flow_mod = build_flow_mod(match_fields=match, actions=actions, priority=100)

    # Verify OpenFlow header
    ver, msg_type, length, xid = struct.unpack("!BBHI", raw_flow_mod[:8])
    assert ver == OFP_VERSION  # 4
    assert msg_type == OFPT_FLOW_MOD  # 14
    assert length == len(raw_flow_mod)


def test_arp_creation_and_parsing():
    reply_pkt = create_arp_reply(
        sender_mac="00:00:00:00:00:fe",
        sender_ip="10.0.0.100",
        target_mac="00:00:00:00:00:01",
        target_ip="10.0.0.1",
    )
    eth = parse_ethernet(reply_pkt)
    assert eth is not None
    assert eth.dst_mac == "00:00:00:00:00:01"
    assert eth.src_mac == "00:00:00:00:00:fe"
    assert eth.eth_type == 0x0806

    arp = parse_arp(eth.payload)
    assert arp is not None
    assert arp.opcode == 2  # Reply
    assert arp.src_ip == "10.0.0.100"
    assert arp.dst_ip == "10.0.0.1"


def test_lb_logic_arp_and_tcp_handling():
    engine = AdaptiveEngine()
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2)
    lb = LoadBalancerLogic("10.0.0.100", "00:00:00:00:00:fe", 8000, engine)

    # 1. Test ARP Request for VIP 10.0.0.100
    arp_req_data = (
        b"\xff\xff\xff\xff\xff\xff"  # dst broadcast
        + b"\x00\x00\x00\x00\x00\x01"  # src h1
        + struct.pack("!H", 0x0806)  # ARP
        + struct.pack("!HHBBH", 1, 0x0800, 6, 4, 1)  # Request
        + b"\x00\x00\x00\x00\x00\x01"
        + bytes([10, 0, 0, 1])
        + b"\x00\x00\x00\x00\x00\x00"
        + bytes([10, 0, 0, 100])
    )
    flow_mods, packet_out = lb.handle_packet_in(in_port=1, raw_data=arp_req_data)
    assert len(flow_mods) == 0
    assert packet_out is not None  # PacketOut containing ARP reply

    # 2. Test TCP SYN packet to VIP 10.0.0.100:8000
    eth_hdr = b"\x00\x00\x00\x00\x00\xfe\x00\x00\x00\x00\x00\x01\x08\x00"
    ip_hdr = struct.pack(
        "!BBHHHBBH4s4s",
        0x45, 0, 40, 1234, 0x4000, 64, 6, 0, bytes([10, 0, 0, 1]), bytes([10, 0, 0, 100])
    )
    tcp_hdr = struct.pack("!HHIIBBHHH", 45678, 8000, 1000, 0, 0x50, 0x02, 65535, 0, 0)  # SYN flag=0x02
    tcp_syn_packet = eth_hdr + ip_hdr + tcp_hdr

    flow_mods, packet_out = lb.handle_packet_in(in_port=1, raw_data=tcp_syn_packet)
    assert len(flow_mods) == 2  # Forward and Reverse FlowMods
    assert packet_out is not None  # Forwarded SYN
    assert (("10.0.0.1", 45678)) in lb.active_sessions
    assert lb.active_sessions[("10.0.0.1", 45678)] == "h2"
