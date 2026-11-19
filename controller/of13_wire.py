from __future__ import annotations

import socket
import struct
from typing import Any, Dict, List

OFP_VERSION = 4

OFPT_HELLO = 0
OFPT_ERROR = 1
OFPT_ECHO_REQUEST = 2
OFPT_ECHO_REPLY = 3
OFPT_FEATURES_REQUEST = 5
OFPT_FEATURES_REPLY = 6
OFPT_PACKET_IN = 10
OFPT_PACKET_OUT = 13
OFPT_FLOW_MOD = 14

OFPFC_ADD = 0
OFPFC_MODIFY = 1
OFPFC_DELETE = 3

OFPIT_APPLY_ACTIONS = 4

OFPAT_OUTPUT = 0
OFPAT_SET_FIELD = 25

OFPP_CONTROLLER = 0xFFFFFFFD
OFPP_FLOOD = 0xFFFFFFFB
OFPP_ALL = 0xFFFFFFFC
OFPP_ANY = 0xFFFFFFFF

OXM_CLASS_OFB = 0x8000
OXM_OFB_IN_PORT = 0
OXM_OFB_ETH_DST = 3
OXM_OFB_ETH_SRC = 4
OXM_OFB_ETH_TYPE = 5
OXM_OFB_IP_PROTO = 10
OXM_OFB_IPV4_SRC = 11
OXM_OFB_IPV4_DST = 12
OXM_OFB_TCP_SRC = 13
OXM_OFB_TCP_DST = 14


def mac_to_bytes(mac: str) -> bytes:
    return bytes(int(part, 16) for part in mac.split(":"))


def bytes_to_mac(data: bytes) -> str:
    return ":".join(f"{value:02x}" for value in data)


def ip_to_bytes(ip: str) -> bytes:
    return socket.inet_aton(ip)


def bytes_to_ip(data: bytes) -> str:
    return socket.inet_ntoa(data)


class OF13Header:
    def __init__(self, msg_type: int, length: int, xid: int = 1, version: int = OFP_VERSION):
        self.version = version
        self.msg_type = msg_type
        self.length = length
        self.xid = xid

    @classmethod
    def parse(cls, data: bytes) -> "OF13Header":
        version, msg_type, length, xid = struct.unpack("!BBHI", data[:8])
        return cls(msg_type, length, xid, version)

    def pack(self) -> bytes:
        return struct.pack("!BBHI", self.version, self.msg_type, self.length, self.xid)


def pack_oxm_tlv(field: int, value: bytes, has_mask: bool = False) -> bytes:
    header = (OXM_CLASS_OFB << 16) | ((field & 0x7F) << 9) | (int(has_mask) << 8) | len(value)
    return struct.pack("!I", header) + value


def pack_match(fields: Dict[str, Any]) -> bytes:
    oxm = bytearray()

    # OXM fields must be ordered by field id.
    if "in_port" in fields:
        oxm.extend(pack_oxm_tlv(OXM_OFB_IN_PORT, struct.pack("!I", fields["in_port"])))
    if "eth_dst" in fields:
        oxm.extend(pack_oxm_tlv(OXM_OFB_ETH_DST, mac_to_bytes(fields["eth_dst"])))
    if "eth_src" in fields:
        oxm.extend(pack_oxm_tlv(OXM_OFB_ETH_SRC, mac_to_bytes(fields["eth_src"])))
    if "eth_type" in fields:
        oxm.extend(pack_oxm_tlv(OXM_OFB_ETH_TYPE, struct.pack("!H", fields["eth_type"])))
    if "ip_proto" in fields:
        oxm.extend(pack_oxm_tlv(OXM_OFB_IP_PROTO, struct.pack("!B", fields["ip_proto"])))
    if "ipv4_src" in fields:
        oxm.extend(pack_oxm_tlv(OXM_OFB_IPV4_SRC, ip_to_bytes(fields["ipv4_src"])))
    if "ipv4_dst" in fields:
        oxm.extend(pack_oxm_tlv(OXM_OFB_IPV4_DST, ip_to_bytes(fields["ipv4_dst"])))
    if "tcp_src" in fields:
        oxm.extend(pack_oxm_tlv(OXM_OFB_TCP_SRC, struct.pack("!H", fields["tcp_src"])))
    if "tcp_dst" in fields:
        oxm.extend(pack_oxm_tlv(OXM_OFB_TCP_DST, struct.pack("!H", fields["tcp_dst"])))

    length = 4 + len(oxm)
    padding = (8 - length % 8) % 8
    return struct.pack("!HH", 1, length) + bytes(oxm) + b"\x00" * padding


def pack_action_output(port: int, max_len: int = 0xFFFF) -> bytes:
    return struct.pack("!HHIH6s", OFPAT_OUTPUT, 16, port, max_len, b"\x00" * 6)


def pack_action_set_field(field: int, value: bytes) -> bytes:
    oxm = pack_oxm_tlv(field, value)
    length = 4 + len(oxm)
    padding = (8 - length % 8) % 8
    return struct.pack("!HH", OFPAT_SET_FIELD, length + padding) + oxm + b"\x00" * padding


def pack_apply_actions_instruction(actions: List[bytes]) -> bytes:
    data = b"".join(actions)
    return struct.pack("!HHI", OFPIT_APPLY_ACTIONS, 8 + len(data), 0) + data


def build_flow_mod(
    match_fields: Dict[str, Any],
    actions: List[bytes],
    priority: int = 100,
    idle_timeout: int = 30,
    hard_timeout: int = 300,
    cookie: int = 0,
    command: int = OFPFC_ADD,
    xid: int = 1,
) -> bytes:
    match = pack_match(match_fields)
    instructions = pack_apply_actions_instruction(actions)

    body = struct.pack(
        "!QQBBHHHIIIHH",
        cookie,
        0,
        0,
        command,
        idle_timeout,
        hard_timeout,
        priority,
        0xFFFFFFFF,
        OFPP_ANY,
        0xFFFFFFFF,
        0,
        0,
    )

    length = 8 + len(body) + len(match) + len(instructions)
    header = struct.pack("!BBHI", OFP_VERSION, OFPT_FLOW_MOD, length, xid)
    return header + body + match + instructions


def build_packet_out(
    in_port: int,
    actions: List[bytes],
    data: bytes,
    buffer_id: int = 0xFFFFFFFF,
    xid: int = 1,
) -> bytes:
    action_data = b"".join(actions)
    body = struct.pack("!IIH6s", buffer_id, in_port, len(action_data), b"\x00" * 6)
    length = 8 + len(body) + len(action_data) + len(data)
    header = struct.pack("!BBHI", OFP_VERSION, OFPT_PACKET_OUT, length, xid)
    return header + body + action_data + data
