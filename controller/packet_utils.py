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


def format_mac(data: bytes) -> str:
    return ":".join(f"{value:02x}" for value in data)


def parse_ethernet(data: bytes) -> Optional[EthernetFrame]:
    if len(data) < 14:
        return None

    dst, src, eth_type = struct.unpack("!6s6sH", data[:14])
    return EthernetFrame(
        dst_mac=format_mac(dst),
        src_mac=format_mac(src),
        eth_type=eth_type,
        payload=data[14:],
    )


def parse_arp(data: bytes) -> Optional[ArpPacket]:
    if len(data) < 28:
        return None

    hw_type, proto_type, hw_size, proto_size, opcode, src_mac, src_ip, dst_mac, dst_ip = struct.unpack(
        "!HHBBH6s4s6s4s", data[:28]
    )
    return ArpPacket(
        hw_type=hw_type,
        proto_type=proto_type,
        hw_size=hw_size,
        proto_size=proto_size,
        opcode=opcode,
        src_mac=format_mac(src_mac),
        src_ip=socket.inet_ntoa(src_ip),
        dst_mac=format_mac(dst_mac),
        dst_ip=socket.inet_ntoa(dst_ip),
    )


def create_arp_reply(sender_mac: str, sender_ip: str, target_mac: str, target_ip: str) -> bytes:
    sender_mac_bytes = bytes(int(part, 16) for part in sender_mac.split(":"))
    target_mac_bytes = bytes(int(part, 16) for part in target_mac.split(":"))
    sender_ip_bytes = socket.inet_aton(sender_ip)
    target_ip_bytes = socket.inet_aton(target_ip)

    ethernet = struct.pack("!6s6sH", target_mac_bytes, sender_mac_bytes, ETH_TYPE_ARP)
    arp = struct.pack(
        "!HHBBH6s4s6s4s",
        1,
        ETH_TYPE_IPV4,
        6,
        4,
        ARP_OP_REPLY,
        sender_mac_bytes,
        sender_ip_bytes,
        target_mac_bytes,
        target_ip_bytes,
    )
    return ethernet + arp


def parse_ipv4(data: bytes) -> Optional[IPv4Packet]:
    if len(data) < 20:
        return None

    (
        version_ihl,
        tos,
        total_length,
        identification,
        flags,
        ttl,
        protocol,
        checksum,
        src_ip,
        dst_ip,
    ) = struct.unpack("!BBHHHBBH4s4s", data[:20])

    version = version_ihl >> 4
    ihl = (version_ihl & 0x0F) * 4
    if ihl < 20 or len(data) < ihl:
        return None

    end = total_length if total_length >= ihl else len(data)
    return IPv4Packet(
        version=version,
        ihl=ihl,
        tos=tos,
        total_length=total_length,
        identification=identification,
        flags=flags,
        ttl=ttl,
        protocol=protocol,
        checksum=checksum,
        src_ip=socket.inet_ntoa(src_ip),
        dst_ip=socket.inet_ntoa(dst_ip),
        payload=data[ihl:end],
    )


def parse_tcp(data: bytes) -> Optional[TcpSegment]:
    if len(data) < 20:
        return None

    src_port, dst_port, seq, ack, offset_reserved, flags, window, checksum, urgent = struct.unpack(
        "!HHIIBBHHH", data[:20]
    )
    data_offset = (offset_reserved >> 4) * 4
    if data_offset < 20 or len(data) < data_offset:
        return None

    return TcpSegment(
        src_port=src_port,
        dst_port=dst_port,
        seq_num=seq,
        ack_num=ack,
        data_offset=data_offset,
        flags=flags,
        window_size=window,
        checksum=checksum,
        urgent_ptr=urgent,
        is_syn=bool(flags & 0x02),
        is_ack=bool(flags & 0x10),
        is_fin=bool(flags & 0x01),
        is_rst=bool(flags & 0x04),
        payload=data[data_offset:],
    )
