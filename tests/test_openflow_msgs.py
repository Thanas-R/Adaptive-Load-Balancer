import struct

from controller.adaptive_engine import AdaptiveEngine
from controller.of13_wire import (
    OFP_VERSION,
    OFPT_FLOW_MOD,
    OFPT_PACKET_OUT,
    OXM_OFB_ETH_DST,
    OXM_OFB_IPV4_DST,
    build_flow_mod,
    build_packet_out,
    ip_to_bytes,
    mac_to_bytes,
    pack_action_output,
    pack_action_set_field,
    pack_match,
)
from controller.openflow_app import LoadBalancerLogic
from controller.packet_utils import (
    ARP_OP_REPLY,
    create_arp_reply,
    parse_arp,
    parse_ethernet,
)


def _oxm_fields(match: bytes) -> list[int]:
    match_type, match_length = struct.unpack("!HH", match[:4])
    assert match_type == 1
    fields = []
    offset = 4
    while offset < match_length:
        header = struct.unpack("!I", match[offset : offset + 4])[0]
        fields.append((header >> 9) & 0x7F)
        offset += 4 + (header & 0xFF)
    return fields


def test_match_length_and_padding():
    match = pack_match({"eth_type": 0x0800})
    match_type, match_length = struct.unpack("!HH", match[:4])

    assert match_type == 1
    assert match_length == 10
    assert len(match) == 16
    assert match[10:] == b"\x00" * 6


def test_empty_match():
    match = pack_match({})
    _, match_length = struct.unpack("!HH", match[:4])

    assert match_length == 4
    assert len(match) == 8


def test_match_fields_are_sorted():
    match = pack_match(
        {
            "tcp_src": 45000,
            "ipv4_src": "10.0.0.1",
            "eth_type": 0x0800,
            "in_port": 1,
        }
    )
    _, match_length = struct.unpack("!HH", match[:4])

    assert _oxm_fields(match) == [0, 5, 11, 13]
    assert match_length == 32
    assert len(match) == 32
    assert match_length % 8 == 0


def test_flow_mod_builder():
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
    flow_mod = build_flow_mod(match_fields=match, actions=actions, priority=100)

    version, message_type, length, _ = struct.unpack("!BBHI", flow_mod[:8])
    assert version == OFP_VERSION
    assert message_type == OFPT_FLOW_MOD
    assert length == len(flow_mod)


def test_packet_out_builder():
    packet_out = build_packet_out(
        in_port=1,
        actions=[pack_action_output(2)],
        data=b"payload",
    )

    version, message_type, length, _ = struct.unpack("!BBHI", packet_out[:8])
    assert version == OFP_VERSION
    assert message_type == OFPT_PACKET_OUT
    assert length == len(packet_out)


def test_arp_creation_and_parsing():
    reply = create_arp_reply(
        sender_mac="00:00:00:00:00:fe",
        sender_ip="10.0.0.100",
        target_mac="00:00:00:00:00:01",
        target_ip="10.0.0.1",
    )
    ethernet = parse_ethernet(reply)
    assert ethernet is not None
    assert ethernet.dst_mac == "00:00:00:00:00:01"
    assert ethernet.src_mac == "00:00:00:00:00:fe"
    assert ethernet.eth_type == 0x0806

    arp = parse_arp(ethernet.payload)
    assert arp is not None
    assert arp.opcode == ARP_OP_REPLY
    assert arp.src_ip == "10.0.0.100"
    assert arp.dst_ip == "10.0.0.1"


def test_load_balancer_arp_and_tcp_handling():
    engine = AdaptiveEngine()
    engine.register_backend("h2", "10.0.0.2", "00:00:00:00:00:02", 8000, 9002, 2)
    lb = LoadBalancerLogic("10.0.0.100", "00:00:00:00:00:fe", 8000, engine)

    arp_request = (
        b"\xff\xff\xff\xff\xff\xff"
        + b"\x00\x00\x00\x00\x00\x01"
        + struct.pack("!H", 0x0806)
        + struct.pack("!HHBBH", 1, 0x0800, 6, 4, 1)
        + b"\x00\x00\x00\x00\x00\x01"
        + bytes([10, 0, 0, 1])
        + b"\x00\x00\x00\x00\x00\x00"
        + bytes([10, 0, 0, 100])
    )
    flow_mods, packet_out = lb.handle_packet_in(in_port=1, raw_data=arp_request)
    assert flow_mods == []
    assert packet_out is not None

    ethernet = b"\x00\x00\x00\x00\x00\xfe\x00\x00\x00\x00\x00\x01\x08\x00"
    ipv4 = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        40,
        1234,
        0x4000,
        64,
        6,
        0,
        bytes([10, 0, 0, 1]),
        bytes([10, 0, 0, 100]),
    )
    tcp = struct.pack("!HHIIBBHHH", 45678, 8000, 1000, 0, 0x50, 0x02, 65535, 0, 0)

    flow_mods, packet_out = lb.handle_packet_in(in_port=1, raw_data=ethernet + ipv4 + tcp)
    assert len(flow_mods) == 2
    assert packet_out is not None
    assert lb.active_sessions[("10.0.0.1", 45678)] == "h2"
