"""Packet parser and serializer for Ethernet, ARP, IPv4, and TCP."""

from __future__ import annotations

import socket
import struct
from typing import NamedTuple, Optional

ETH_TYPE_IPV4 = 0x0800
ETH_TYPE_ARP = 0x0806

ARP_OP_REQUEST = 1
ARP_OP_REPLY = 2

IP_PROTO_TCP = 6
IP_PROTO_UDP = 17
IP_PROTO_ICMP = 1


class EthernetFrame(NamedTuple):
    dst_mac: str
    src_mac: str
    eth_type: int
    payload: bytes


class ArpPacket(NamedTuple):
    hw_type: int
    proto_type: int
    hw_size: int
    proto_size: int
    opcode: int
    src_mac: str
    src_ip: str
    dst_mac: str
    dst_ip: str


class IPv4Packet(NamedTuple):
    version: int
    ihl: int
    tos: int
    total_length: int
    identification: int
    flags: int
    ttl: int
    protocol: int
    checksum: int
    src_ip: str
    dst_ip: str
    payload: bytes


class TcpSegment(NamedTuple):
    src_port: int
    dst_port: int
    seq_num: int
    ack_num: int
    data_offset: int
    flags: int
    window_size: int
    checksum: int
    urgent_ptr: int
    is_syn: bool
    is_ack: bool
    is_fin: bool
    is_rst: bool
    payload: bytes


def format_mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def parse_ethernet(data: bytes) -> Optional[EthernetFrame]:
    if len(data) < 14:
        return None
    dst_mac_raw, src_mac_raw, eth_type = struct.unpack("!6s6sH", data[:14])
    return EthernetFrame(
        dst_mac=format_mac(dst_mac_raw),
        src_mac=format_mac(src_mac_raw),
        eth_type=eth_type,
        payload=data[14:],
    )


def parse_arp(data: bytes) -> Optional[ArpPacket]:
    if len(data) < 28:
        return None
    hw_t, proto_t, hw_s, proto_s, op, s_mac, s_ip, d_mac, d_ip = struct.unpack("!HHBBH6s4s6s4s", data[:28])
    return ArpPacket(
        hw_type=hw_t,
        proto_type=proto_t,
        hw_size=hw_s,
        proto_size=proto_s,
        opcode=op,
        src_mac=format_mac(s_mac),
        src_ip=socket.inet_ntoa(s_ip),
        dst_mac=format_mac(d_mac),
        dst_ip=socket.inet_ntoa(d_ip),
    )


def create_arp_reply(
    sender_mac: str,
    sender_ip: str,
    target_mac: str,
    target_ip: str,
) -> bytes:
    """Build an Ethernet + ARP reply packet."""
    s_mac_bytes = bytes(int(x, 16) for x in sender_mac.split(":"))
    t_mac_bytes = bytes(int(x, 16) for x in target_mac.split(":"))
    s_ip_bytes = socket.inet_aton(sender_ip)
    t_ip_bytes = socket.inet_aton(target_ip)

    eth_hdr = struct.pack("!6s6sH", t_mac_bytes, s_mac_bytes, ETH_TYPE_ARP)
    arp_hdr = struct.pack(
        "!HHBBH6s4s6s4s",
        1,  # Ethernet
        ETH_TYPE_IPV4,
        6,  # MAC len
        4,  # IP len
        ARP_OP_REPLY,
        s_mac_bytes,
        s_ip_bytes,
        t_mac_bytes,
        t_ip_bytes,
    )
    return eth_hdr + arp_hdr


def parse_ipv4(data: bytes) -> Optional[IPv4Packet]:
    if len(data) < 20:
        return None
    v_ihl, tos, tot_len, ident, flags_frag, ttl, proto, csum, s_ip, d_ip = struct.unpack("!BBHHHBBH4s4s", data[:20])
    version = v_ihl >> 4
    ihl = (v_ihl & 0x0F) * 4
    if len(data) < ihl:
        return None
    return IPv4Packet(
        version=version,
        ihl=ihl,
        tos=tos,
        total_length=tot_len,
        identification=ident,
        flags=flags_frag,
        ttl=ttl,
        protocol=proto,
        checksum=csum,
        src_ip=socket.inet_ntoa(s_ip),
        dst_ip=socket.inet_ntoa(d_ip),
        payload=data[ihl:tot_len] if tot_len > 0 else data[ihl:],
    )


def parse_tcp(data: bytes) -> Optional[TcpSegment]:
    if len(data) < 20:
        return None
    s_port, d_port, seq, ack, offset_reserved, flags, win, csum, urg = struct.unpack("!HHIIBBHHH", data[:20])
    data_offset = (offset_reserved >> 4) * 4
    if len(data) < data_offset:
        return None
    return TcpSegment(
        src_port=s_port,
        dst_port=d_port,
        seq_num=seq,
        ack_num=ack,
        data_offset=data_offset,
        flags=flags,
        window_size=win,
        checksum=csum,
        urgent_ptr=urg,
        is_syn=bool(flags & 0x02),
        is_ack=bool(flags & 0x10),
        is_fin=bool(flags & 0x01),
        is_rst=bool(flags & 0x04),
        payload=data[data_offset:],
    )
