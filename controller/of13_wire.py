"""OpenFlow 1.3 Wire Protocol Parser and Serializer.

Implements binary parsing and packing for OpenFlow 1.3 messages:
- OFPT_HELLO (0)
- OFPT_ECHO_REQUEST (2) / OFPT_ECHO_REPLY (3)
- OFPT_FEATURES_REQUEST (5) / OFPT_FEATURES_REPLY (6)
- OFPT_PACKET_IN (10)
- OFPT_FLOW_MOD (14)
- OFPT_PACKET_OUT (13)
- OXM Match Fields & Instructions (OFPIT_APPLY_ACTIONS)
- Action: OFPAT_OUTPUT (0), OFPAT_SET_FIELD (25)
"""

from __future__ import annotations

import socket
import struct
from typing import Dict, List, Optional, Tuple

OFP_VERSION = 4  # OpenFlow 1.3

# Message types
OFPT_HELLO = 0
OFPT_ERROR = 1
OFPT_ECHO_REQUEST = 2
OFPT_ECHO_REPLY = 3
OFPT_FEATURES_REQUEST = 5
OFPT_FEATURES_REPLY = 6
OFPT_PACKET_IN = 10
OFPT_PACKET_OUT = 13
OFPT_FLOW_MOD = 14

# Flow Mod Commands
OFPFC_ADD = 0
OFPFC_MODIFY = 1
OFPFC_DELETE = 3

# Flow Mod Flags
OFPFF_SEND_FLOW_REM = 1

# Instructions
OFPIT_APPLY_ACTIONS = 4

# Actions
OFPAT_OUTPUT = 0
OFPAT_SET_FIELD = 25

# Special ports
OFPP_CONTROLLER = 0xFFFFFFFD
OFPP_FLOOD = 0xFFFFFFFB
OFPP_ALL = 0xFFFFFFFC
OFPP_ANY = 0xFFFFFFFF


def mac_to_bytes(mac_str: str) -> bytes:
    return bytes(int(b, 16) for b in mac_str.split(":"))


def bytes_to_mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def ip_to_bytes(ip_str: str) -> bytes:
    return socket.inet_aton(ip_str)


def bytes_to_ip(b: bytes) -> str:
    return socket.inet_ntoa(b)


class OF13Header:
    def __init__(self, msg_type: int, length: int, xid: int = 1):
        self.version = OFP_VERSION
        self.msg_type = msg_type
        self.length = length
        self.xid = xid

    @classmethod
    def parse(cls, data: bytes) -> OF13Header:
        version, msg_type, length, xid = struct.unpack("!BBHI", data[:8])
        return cls(msg_type, length, xid)

    def pack(self) -> bytes:
        return struct.pack("!BBHI", self.version, self.msg_type, self.length, self.xid)


# OXM definitions: class=0x8000 (OpenFlow basic)
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


def pack_oxm_tlv(field: int, val_bytes: bytes, has_mask: bool = False) -> bytes:
    header = (OXM_CLASS_OFB << 16) | ((field & 0x7F) << 9) | ((1 if has_mask else 0) << 8) | len(val_bytes)
    return struct.pack("!I", header) + val_bytes


def pack_match(fields: Dict[str, any]) -> bytes:
    """Pack an OpenFlow 1.3 OFPMatch structure (type=1, length, oxm_fields, padding)."""
    oxm_bytes = bytearray()
    if "in_port" in fields:
        oxm_bytes.extend(pack_oxm_tlv(OXM_OFB_IN_PORT, struct.pack("!I", fields["in_port"])))
    if "eth_type" in fields:
        oxm_bytes.extend(pack_oxm_tlv(OXM_OFB_ETH_TYPE, struct.pack("!H", fields["eth_type"])))
    if "eth_src" in fields:
        oxm_bytes.extend(pack_oxm_tlv(OXM_OFB_ETH_SRC, mac_to_bytes(fields["eth_src"])))
    if "eth_dst" in fields:
        oxm_bytes.extend(pack_oxm_tlv(OXM_OFB_ETH_DST, mac_to_bytes(fields["eth_dst"])))
    if "ip_proto" in fields:
        oxm_bytes.extend(pack_oxm_tlv(OXM_OFB_IP_PROTO, struct.pack("!B", fields["ip_proto"])))
    if "ipv4_src" in fields:
        oxm_bytes.extend(pack_oxm_tlv(OXM_OFB_IPV4_SRC, ip_to_bytes(fields["ipv4_src"])))
    if "ipv4_dst" in fields:
        oxm_bytes.extend(pack_oxm_tlv(OXM_OFB_IPV4_DST, ip_to_bytes(fields["ipv4_dst"])))
    if "tcp_src" in fields:
        oxm_bytes.extend(pack_oxm_tlv(OXM_OFB_TCP_SRC, struct.pack("!H", fields["tcp_src"])))
    if "tcp_dst" in fields:
        oxm_bytes.extend(pack_oxm_tlv(OXM_OFB_TCP_DST, struct.pack("!H", fields["tcp_dst"])))

    # OFPMatch header: type (2 bytes = 1), length (2 bytes = 4 + len(oxm))
    length = 4 + len(oxm_bytes)
    # Pad to 8-byte boundary
    pad_len = (8 - (length % 8)) % 8
    pad = b"\x00" * pad_len
    total_len = length + pad_len
    return struct.pack("!HH", 1, total_len) + bytes(oxm_bytes) + pad


def pack_action_output(port: int, max_len: int = 0xFFFF) -> bytes:
    """Action OFPAT_OUTPUT: type=0 (2B), len=16 (2B), port (4B), max_len (2B), pad (6B)."""
    return struct.pack("!HHIH6s", OFPAT_OUTPUT, 16, port, max_len, b"\x00" * 6)


def pack_action_set_field(field: int, val_bytes: bytes) -> bytes:
    """Action OFPAT_SET_FIELD: type=25 (2B), len (2B), oxm_tlv, padding to 8-byte."""
    oxm = pack_oxm_tlv(field, val_bytes)
    raw_len = 4 + len(oxm)
    pad_len = (8 - (raw_len % 8)) % 8
    total_len = raw_len + pad_len
    return struct.pack("!HH", OFPAT_SET_FIELD, total_len) + oxm + (b"\x00" * pad_len)


def pack_apply_actions_instruction(actions: List[bytes]) -> bytes:
    """Instruction OFPIT_APPLY_ACTIONS: type=4 (2B), len (2B), pad (4B), actions."""
    action_data = b"".join(actions)
    inst_len = 8 + len(action_data)
    return struct.pack("!HHI", OFPIT_APPLY_ACTIONS, inst_len, 0) + action_data


def build_flow_mod(
    match_fields: Dict[str, any],
    actions: List[bytes],
    priority: int = 100,
    idle_timeout: int = 30,
    hard_timeout: int = 300,
    cookie: int = 0,
    command: int = OFPFC_ADD,
    xid: int = 1,
) -> bytes:
    """Construct an OpenFlow 1.3 OFPT_FLOW_MOD binary packet."""
    match_bytes = pack_match(match_fields)
    instruction_bytes = pack_apply_actions_instruction(actions)
    
    # OFPFlowMod body:
    # cookie (8B), cookie_mask (8B), table_id (1B), command (1B),
    # idle_timeout (2B), hard_timeout (2B), priority (2B),
    # buffer_id (4B), out_port (4B), out_group (4B), flags (2B), pad (2B)
    buffer_id = 0xFFFFFFFF  # OFP_NO_BUFFER
    out_port = OFPP_ANY
    out_group = 0xFFFFFFFF  # OFPG_ANY
    flags = 0

    body = struct.pack(
        "!QQBBHHHIIIHH",
        cookie,
        0,  # cookie_mask
        0,  # table_id
        command,
        idle_timeout,
        hard_timeout,
        priority,
        buffer_id,
        out_port,
        out_group,
        flags,
        0,  # pad
    )

    total_len = 8 + len(body) + len(match_bytes) + len(instruction_bytes)
    hdr = struct.pack("!BBHI", OFP_VERSION, OFPT_FLOW_MOD, total_len, xid)
    return hdr + body + match_bytes + instruction_bytes


def build_packet_out(
    in_port: int,
    actions: List[bytes],
    data: bytes,
    buffer_id: int = 0xFFFFFFFF,
    xid: int = 1,
) -> bytes:
    """Construct an OpenFlow 1.3 OFPT_PACKET_OUT message."""
    action_data = b"".join(actions)
    actions_len = len(action_data)
    # Header (8B) + buffer_id (4B) + in_port (4B) + actions_len (2B) + pad (6B) + actions + data
    body_hdr = struct.pack("!IIH6s", buffer_id, in_port, actions_len, b"\x00" * 6)
    total_len = 8 + len(body_hdr) + actions_len + len(data)
    hdr = struct.pack("!BBHI", OFP_VERSION, OFPT_PACKET_OUT, total_len, xid)
    return hdr + body_hdr + action_data + data
