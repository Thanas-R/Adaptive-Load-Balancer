"""Ryu-based OpenFlow 1.3 SDN Adaptive Load Balancer.

Can be run via:
    ryu-manager controller/ryu_controller.py
"""

from __future__ import annotations

import json
import logging
import os
import sys

from controller.adaptive_engine import AdaptiveEngine
from controller.telemetry_collector import TelemetryCollector

logger = logging.getLogger("ryu_lb_controller")

try:
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
    from ryu.lib.packet import arp, ethernet, ipv4, packet, tcp
    from ryu.ofproto import ofproto_v1_3
    RYU_AVAILABLE = True
except ImportError:
    RYU_AVAILABLE = False
    # Define placeholder class if Ryu is not installed in current environment
    class DummyApp:
        pass
    app_manager = type("obj", (object,), {"RyuApp": DummyApp})


class RyuAdaptiveLoadBalancer(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION] if RYU_AVAILABLE else [4]

    def __init__(self, *args, **kwargs):
        super(RyuAdaptiveLoadBalancer, self).__init__(*args, **kwargs)
        if not RYU_AVAILABLE:
            logger.error("Ryu framework is not installed in this Python environment.")
            return

        # Load global configuration
        config_path = os.environ.get("SDN_CONFIG", "config.json")
        with open(config_path, "r") as f:
            self.config = json.load(f)

        net_cfg = self.config["network"]
        alg_cfg = self.config["algorithm"]
        ctrl_cfg = self.config["controller"]

        self.vip = net_cfg["vip"]
        self.vip_mac = net_cfg["vip_mac"]
        self.service_port = net_cfg["service_port"]
        self.flow_idle_timeout = ctrl_cfg.get("flow_idle_timeout", 30)
        self.flow_hard_timeout = ctrl_cfg.get("flow_hard_timeout", 300)

        # Initialize adaptive scoring engine
        self.engine = AdaptiveEngine(
            weights=alg_cfg.get("weights"),
            ema_alpha=alg_cfg.get("ema_alpha", 0.25),
            max_consecutive_failures=alg_cfg.get("health_check", {}).get("max_consecutive_failures", 3),
            recovery_cooldown_sec=alg_cfg.get("health_check", {}).get("recovery_cooldown_sec", 5.0),
            mode=alg_cfg.get("mode", "adaptive"),
        )

        # Register backend instances
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

        # Start background telemetry collector
        probe_interval = alg_cfg.get("health_check", {}).get("probe_interval_sec", 1.0)
        self.telemetry = TelemetryCollector(self.engine, probe_interval=probe_interval)
        self.telemetry.start()
        logger.info("Ryu Adaptive Load Balancer Initialized.")

    if RYU_AVAILABLE:
        @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
        def switch_features_handler(self, ev):
            # Install default table-miss entry to forward unhandled packets to controller
            datapath = ev.msg.datapath
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser

            match = parser.OFPMatch()
            actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
            mod = parser.OFPFlowMod(
                datapath=datapath, priority=0, match=match, instructions=inst
            )
            datapath.send_msg(mod)
            logger.info(f"Installed table-miss flow rule on Datapath ID {datapath.id}")

        @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
        def packet_in_handler(self, ev):
            # Inspect packet-in events for ARP and TCP VIP traffic
            msg = ev.msg
            datapath = msg.datapath
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            in_port = msg.match["in_port"]

            pkt = packet.Packet(msg.data)
            eth = pkt.get_protocols(ethernet.ethernet)[0]

            # Handle ARP Requests for VIP by returning synthetic ARP reply
            arp_pkt = pkt.get_protocol(arp.arp)
            if arp_pkt:
                if arp_pkt.opcode == arp.ARP_REQUEST and arp_pkt.dst_ip == self.vip:
                    reply_pkt = packet.Packet()
                    reply_pkt.add_protocol(ethernet.ethernet(
                        dst=eth.src,
                        src=self.vip_mac,
                        ethertype=eth.ethertype
                    ))
                    reply_pkt.add_protocol(arp.arp(
                        opcode=arp.ARP_REPLY,
                        src_mac=self.vip_mac,
                        src_ip=self.vip,
                        dst_mac=arp_pkt.src_mac,
                        dst_ip=arp_pkt.src_ip
                    ))
                    reply_pkt.serialize()

                    actions = [parser.OFPActionOutput(in_port)]
                    out = parser.OFPPacketOut(
                        datapath=datapath,
                        buffer_id=ofproto.OFP_NO_BUFFER,
                        in_port=ofproto.OFPP_CONTROLLER,
                        actions=actions,
                        data=reply_pkt.data
                    )
                    datapath.send_msg(out)
                    return

            # Handle TCP Traffic destined for VIP
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            tcp_pkt = pkt.get_protocol(tcp.tcp)
            if ip_pkt and tcp_pkt and ip_pkt.dst == self.vip and tcp_pkt.dst_port == self.service_port:
                client_ip = ip_pkt.src
                client_port = tcp_pkt.src_port

                # Select best server from adaptive engine
                backend = self.engine.select_backend()
                if not backend:
                    logger.error("No healthy backend server available!")
                    return

                logger.info(f"Ryu routing flow {client_ip}:{client_port} -> VIP => {backend.server_id} ({backend.ip})")

                # Forward Flow: Client -> Switch -> Backend (rewrite destination IP and MAC)
                match_fwd = parser.OFPMatch(
                    in_port=in_port,
                    eth_type=0x0800,
                    ip_proto=6,
                    ipv4_src=client_ip,
                    ipv4_dst=self.vip,
                    tcp_src=client_port,
                    tcp_dst=self.service_port,
                )
                actions_fwd = [
                    parser.OFPActionSetField(eth_dst=backend.mac),
                    parser.OFPActionSetField(ipv4_dst=backend.ip),
                    parser.OFPActionOutput(backend.switch_port),
                ]
                inst_fwd = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions_fwd)]
                mod_fwd = parser.OFPFlowMod(
                    datapath=datapath,
                    priority=100,
                    idle_timeout=self.flow_idle_timeout,
                    hard_timeout=self.flow_hard_timeout,
                    match=match_fwd,
                    instructions=inst_fwd,
                )
                datapath.send_msg(mod_fwd)

                # Reverse Flow: Backend -> Switch -> Client (rewrite source IP and MAC to VIP)
                match_rev = parser.OFPMatch(
                    in_port=backend.switch_port,
                    eth_type=0x0800,
                    ip_proto=6,
                    ipv4_src=backend.ip,
                    ipv4_dst=client_ip,
                    tcp_src=backend.service_port,
                    tcp_dst=client_port,
                )
                actions_rev = [
                    parser.OFPActionSetField(eth_src=self.vip_mac),
                    parser.OFPActionSetField(ipv4_src=self.vip),
                    parser.OFPActionOutput(in_port),
                ]
                inst_rev = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions_rev)]
                mod_rev = parser.OFPFlowMod(
                    datapath=datapath,
                    priority=100,
                    idle_timeout=self.flow_idle_timeout,
                    hard_timeout=self.flow_hard_timeout,
                    match=match_rev,
                    instructions=inst_rev,
                )
                datapath.send_msg(mod_rev)

                # Send buffered packet out to chosen backend
                out = parser.OFPPacketOut(
                    datapath=datapath,
                    buffer_id=msg.buffer_id,
                    in_port=in_port,
                    actions=actions_fwd,
                    data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None,
                )
                datapath.send_msg(out)
