#!/usr/bin/env python3
"""Mininet SDN Topology for Adaptive Load Balancing.

Creates:
- h1: Client host generating TCP requests
- h2, h3, h4: Backend servers running TCP socket workers and telemetry agents
- s1: Open vSwitch running OpenFlow 1.3
- Remote SDN Controller: listening on 127.0.0.1:6653
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    from mininet.cli import CLI
    from mininet.log import info, setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSSwitch, RemoteController
    from mininet.topo import Topo
    MININET_AVAILABLE = True
except ImportError:
    MININET_AVAILABLE = False


class SDNLoadBalancerTopo(Topo):
    def build(self, config: dict):
        # Add Open vSwitch s1 configured for OpenFlow 1.3
        s1 = self.addSwitch("s1", protocols="OpenFlow13", dpid="0000000000000001")

        # Add Client h1 and link to switch port 1
        client_cfg = config["client"]
        h1 = self.addHost(
            client_cfg["id"],
            ip=f"{client_cfg['ip']}/24",
            mac=client_cfg["mac"],
        )
        self.addLink(h1, s1, port1=0, port2=client_cfg["switch_port"])

        # Add Backend Hosts h2, h3, h4 linked to their respective switch ports
        for b in config["backends"]:
            h = self.addHost(
                b["id"],
                ip=f"{b['ip']}/24",
                mac=b["mac"],
            )
            self.addLink(h, s1, port1=0, port2=b["switch_port"])


def start_backend_processes(net: Mininet, config: dict):
    # Launch backend TCP servers and telemetry agents inside host network namespaces
    info("*** Starting TCP backend workers and telemetry agents...\n")
    for b in config["backends"]:
        host = net.get(b["id"])
        # Disable TCP checksum offloading to ensure clean namespace TCP emulation
        host.cmd(f"ethtool -K {b['id']}-eth0 tx off rx off 2>/dev/null")

        cmd = (
            f"python3 -m backend.server "
            f"--id {b['id']} "
            f"--ip {b['ip']} "
            f"--port {b['service_port']} "
            f"--telemetry-port {b['telemetry_port']} "
            f"--delay {b.get('initial_delay_ms', 20.0)} "
            f"> logs/{b['id']}.log 2>&1 &"
        )
        info(f"  Starting {b['id']}: {cmd}\n")
        host.cmd(cmd)

    # Disable offload on client interface
    client_id = config["client"]["id"]
    client_host = net.get(client_id)
    client_host.cmd(f"ethtool -K {client_id}-eth0 tx off rx off 2>/dev/null")
    info("*** All backend processes launched successfully.\n")


def run(config_path: str = "config.json", interactive: bool = True):
    # Main runner function to start topology and link controller
    if not MININET_AVAILABLE:
        print("ERROR: Mininet is not installed or not available in this Python environment.")
        print("Please run this script on an Ubuntu Linux system with Mininet and OVS installed.")
        sys.exit(1)

    os.makedirs("logs", exist_ok=True)
    with open(config_path, "r") as f:
        config = json.load(f)

    ctrl_cfg = config["controller"]
    setLogLevel("info")

    # Instantiate Mininet topology
    topo = SDNLoadBalancerTopo(config)
    net = Mininet(
        topo=topo,
        switch=OVSSwitch,
        controller=None,
        autoSetMacs=False,
        autoStaticArp=False,
    )

    # Connect to external remote SDN controller
    info("*** Connecting to Remote SDN Controller at 127.0.0.1:6653...\n")
    net.addController(
        "c0",
        controller=RemoteController,
        ip=ctrl_cfg.get("of_host", "127.0.0.1"),
        port=ctrl_cfg.get("of_port", 6653),
    )

    net.start()

    # Wait for switch connection to controller
    info("*** Waiting for Open vSwitch handshake with SDN Controller...\n")
    time.sleep(2)

    # Spawn backend socket servers and telemetry daemons
    start_backend_processes(net, config)

    # Interactive Mininet CLI or programmatic return
    if interactive:
        info("\n*** SDN Load Balancer Network Ready!\n")
        info(f"*** Virtual IP: {config['network']['vip']}:{config['network']['service_port']}\n")
        info("*** Type 'exit' to terminate Mininet.\n")
        CLI(net)
        net.stop()
    else:
        return net


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mininet SDN Load Balancer Topology")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--non-interactive", action="store_true", help="Start without interactive CLI")
    args = parser.parse_args()

    run(config_path=args.config, interactive=not args.non_interactive)
