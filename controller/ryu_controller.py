from __future__ import annotations

import logging
import os
import sys

from controller.adaptive_engine import AdaptiveEngine
from controller.config import load_config, project_root
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

    class DummyApp:
        pass

    app_manager = type("AppManager", (object,), {"RyuApp": DummyApp})


class RyuAdaptiveLoadBalancer(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION] if RYU_AVAILABLE else [4]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not RYU_AVAILABLE:
            logger.error("Ryu is not installed")
            return

        config = load_config(os.environ.get("SDN_CONFIG", "config.json"))
        network = config["network"]
        algorithm = config["algorithm"]
        controller = config["controller"]

        self.vip = network["vip"]
        self.vip_mac = network["vip_mac"]
        self.service_port = network["service_port"]
        self.flow_idle_timeout = controller.get("flow_idle_timeout", 30)
        self.flow_hard_timeout = controller.get("flow_hard_timeout", 300)

        self.engine = AdaptiveEngine(
            weights=algorithm.get("weights"),
            ema_alpha=algorithm.get("ema_alpha", 0.25),
            max_consecutive_failures=algorithm.get("health_check", {}).get("max_consecutive_failures", 3),
            recovery_cooldown_sec=algorithm.get("health_check", {}).get("recovery_cooldown_sec", 5.0),
            degraded_latency_ms=algorithm.get("degraded_latency_ms", 150.0),
            latency_tolerance_ms=algorithm.get("latency_tolerance_ms", 5.0),
            mode=algorithm.get("mode", "adaptive"),
        )

        for backend in config["backends"]:
            self.engine.register_backend(
                server_id=backend["id"],
                ip=backend["ip"],
                mac=backend["mac"],
                service_port=backend["service_port"],
                telemetry_port=backend["telemetry_port"],
                switch_port=backend["switch_port"],
                capacity=backend.get("capacity", 100),
                initial_delay_ms=backend.get("initial_delay_ms", 20.0),
                telemetry_ip=backend.get("telemetry_ip"),
            )

        interval = algorithm.get("health_check", {}).get("probe_interval_sec", 1.0)
        self.telemetry = TelemetryCollector(self.engine, probe_interval=interval)
        self.telemetry.start()
        logger.info("Adaptive load balancer ready, VIP %s:%s", self.vip, self.service_port)

    if RYU_AVAILABLE:

        @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
        def switch_features_handler(self, ev):
            datapath = ev.msg.datapath
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser

            # Table-miss sends unknown packets to the controller
            actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
            instructions = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
            flow = parser.OFPFlowMod(datapath=datapath, priority=0, match=parser.OFPMatch(), instructions=instructions)
            datapath.send_msg(flow)
            logger.info("Table-miss installed on datapath %s", datapath.id)

        @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
        def packet_in_handler(self, ev):
            msg = ev.msg
            datapath = msg.datapath
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            in_port = msg.match["in_port"]

            received = packet.Packet(msg.data)
            eth = received.get_protocol(ethernet.ethernet)
            if not eth:
                return

            arp_packet = received.get_protocol(arp.arp)
            if arp_packet and arp_packet.opcode == arp.ARP_REQUEST and arp_packet.dst_ip == self.vip:
                reply = packet.Packet()
                reply.add_protocol(
                    ethernet.ethernet(dst=eth.src, src=self.vip_mac, ethertype=eth.ethertype)
                )
                reply.add_protocol(
                    arp.arp(
                        opcode=arp.ARP_REPLY,
                        src_mac=self.vip_mac,
                        src_ip=self.vip,
                        dst_mac=arp_packet.src_mac,
                        dst_ip=arp_packet.src_ip,
                    )
                )
                reply.serialize()
                actions = [parser.OFPActionOutput(in_port)]
                out = parser.OFPPacketOut(
                    datapath=datapath,
                    buffer_id=ofproto.OFP_NO_BUFFER,
                    in_port=ofproto.OFPP_CONTROLLER,
                    actions=actions,
                    data=reply.data,
                )
                datapath.send_msg(out)
                return

            ipv4_packet = received.get_protocol(ipv4.ipv4)
            tcp_packet = received.get_protocol(tcp.tcp)
            if not ipv4_packet or not tcp_packet:
                return
            if ipv4_packet.dst != self.vip or tcp_packet.dst_port != self.service_port:
                return

            backend = self.engine.select_backend()
            if not backend:
                logger.error("No backend available for %s:%s", ipv4_packet.src, tcp_packet.src_port)
                return

            logger.info(
                "Flow %s:%s -> %s, backend %s (%s)",
                ipv4_packet.src,
                tcp_packet.src_port,
                self.vip,
                backend.server_id,
                backend.ip,
            )

            # Forward path: client to backend
            forward_match = parser.OFPMatch(
                in_port=in_port,
                eth_type=0x0800,
                ip_proto=6,
                ipv4_src=ipv4_packet.src,
                ipv4_dst=self.vip,
                tcp_src=tcp_packet.src_port,
                tcp_dst=self.service_port,
            )
            forward_actions = [
                parser.OFPActionSetField(eth_dst=backend.mac),
                parser.OFPActionSetField(ipv4_dst=backend.ip),
                parser.OFPActionOutput(backend.switch_port),
            ]
            forward = parser.OFPFlowMod(
                datapath=datapath,
                priority=100,
                idle_timeout=self.flow_idle_timeout,
                hard_timeout=self.flow_hard_timeout,
                match=forward_match,
                instructions=[
                    parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, forward_actions)
                ],
            )
            datapath.send_msg(forward)

            # Reverse path: backend to client, source rewritten to the VIP
            reverse_match = parser.OFPMatch(
                in_port=backend.switch_port,
                eth_type=0x0800,
                ip_proto=6,
                ipv4_src=backend.ip,
                ipv4_dst=ipv4_packet.src,
                tcp_src=backend.service_port,
                tcp_dst=tcp_packet.src_port,
            )
            reverse_actions = [
                parser.OFPActionSetField(eth_src=self.vip_mac),
                parser.OFPActionSetField(ipv4_src=self.vip),
                parser.OFPActionOutput(in_port),
            ]
            reverse = parser.OFPFlowMod(
                datapath=datapath,
                priority=100,
                idle_timeout=self.flow_idle_timeout,
                hard_timeout=self.flow_hard_timeout,
                match=reverse_match,
                instructions=[
                    parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, reverse_actions)
                ],
            )
            datapath.send_msg(reverse)

            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=forward_actions,
                data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None,
            )
            datapath.send_msg(out)


def main() -> None:
    if not RYU_AVAILABLE:
        raise SystemExit("Ryu is not installed. Install it on Linux or use controller.standalone_controller")

    from ryu.cmd.manager import main as ryu_main

    config = load_config(os.environ.get("SDN_CONFIG", "config.json"))
    controller = config["controller"]
    root = project_root()
    if root not in sys.path:
        sys.path.insert(0, root)

    sys.argv = [
        "ryu-manager",
        "--ofp-listen-host",
        str(controller.get("of_host", "0.0.0.0")),
        "--ofp-tcp-listen-port",
        str(controller.get("of_port", 6653)),
        os.path.abspath(__file__),
    ]
    ryu_main()


if __name__ == "__main__":
    main()
