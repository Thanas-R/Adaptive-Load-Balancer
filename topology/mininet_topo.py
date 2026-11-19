from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time

from controller.config import load_config, project_root

try:
    from mininet.cli import CLI
    from mininet.log import info, setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSSwitch, RemoteController
    from mininet.topo import Topo

    MININET_AVAILABLE = True
except ImportError:
    MININET_AVAILABLE = False

    class Topo:
        def __init__(self, **kwargs):
            pass

    CLI = None
    Mininet = object
    OVSSwitch = object
    RemoteController = object

    def info(message: str) -> None:
        print(message)

    def setLogLevel(level: str) -> None:
        return None


CONTROL_BRIDGE = "alb-ctl"


class SDNLoadBalancerTopo(Topo):
    def __init__(self, config: dict, **kwargs):
        self.config = config
        super().__init__(**kwargs)

    def build(self):
        config = self.config
        client = config["client"]

        # topology
        switch = self.addSwitch("s1", protocols="OpenFlow13", dpid="0000000000000001")
        client_host = self.addHost(
            client["id"],
            ip=f"{client['ip']}/24",
            mac=client["mac"],
        )
        self.addLink(client_host, switch, port2=client["switch_port"])

        for backend in config["backends"]:
            host = self.addHost(
                backend["id"],
                ip=f"{backend['ip']}/24",
                mac=backend["mac"],
            )
            self.addLink(host, switch, port2=backend["switch_port"])


def run_command(args: list[str]) -> bool:
    result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return result.returncode == 0


def cleanup_control_network(config: dict) -> None:
    for backend in config["backends"]:
        run_command(["ip", "link", "del", f"ctl-{backend['id']}"])
    run_command(["ip", "link", "del", CONTROL_BRIDGE])


def setup_control_network(net: "Mininet", config: dict) -> None:
    network = config["network"]
    control_ip = network.get("control_ip", "192.168.50.1")

    # control network for telemetry, outside the OpenFlow datapath
    cleanup_control_network(config)
    if not run_command(["ip", "link", "add", CONTROL_BRIDGE, "type", "bridge"]):
        info("*** Could not create telemetry control bridge\n")
        return

    run_command(["ip", "addr", "replace", f"{control_ip}/24", "dev", CONTROL_BRIDGE])
    run_command(["ip", "link", "set", CONTROL_BRIDGE, "up"])

    for backend in config["backends"]:
        telemetry_ip = backend.get("telemetry_ip")
        if not telemetry_ip:
            continue

        host = net.get(backend["id"])
        root_if = f"ctl-{backend['id']}"
        host_if = f"{backend['id']}-ctl"
        if not run_command(["ip", "link", "add", root_if, "type", "veth", "peer", "name", host_if]):
            continue

        run_command(["ip", "link", "set", root_if, "master", CONTROL_BRIDGE])
        run_command(["ip", "link", "set", root_if, "up"])
        run_command(["ip", "link", "set", host_if, "netns", str(host.pid)])
        host.cmd(f"ip addr replace {telemetry_ip}/24 dev {host_if}")
        host.cmd(f"ip link set {host_if} up")

    info(f"*** Telemetry control network ready on {control_ip}\n")


def wait_for_switch(net: "Mininet", timeout: float = 10.0) -> bool:
    switch = net.get("s1")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if switch.connected():
            return True
        time.sleep(0.5)
    return False


def start_backend_processes(net: "Mininet", config: dict) -> None:
    info("*** Starting backend servers and telemetry agents\n")
    root = project_root()
    log_dir = os.path.join(root, "logs")
    os.makedirs(log_dir, exist_ok=True)

    for backend in config["backends"]:
        host = net.get(backend["id"])
        host.cmd(f"ethtool -K {backend['id']}-eth0 tx off rx off 2>/dev/null || true")

        log_path = os.path.join(log_dir, f"{backend['id']}.log")
        telemetry_ip = backend.get("telemetry_ip", backend["ip"])
        command = (
            f"cd {shlex.quote(root)} && "
            f"{shlex.quote(sys.executable)} -m backend.server "
            f"--id {backend['id']} "
            f"--ip {backend['ip']} "
            f"--port {backend['service_port']} "
            f"--telemetry-ip {telemetry_ip} "
            f"--telemetry-port {backend['telemetry_port']} "
            f"--delay {backend.get('initial_delay_ms', 20.0)} "
            f"> {shlex.quote(log_path)} 2>&1 &"
        )
        host.cmd(command)

    client = config["client"]
    net.get(client["id"]).cmd(f"ethtool -K {client['id']}-eth0 tx off rx off 2>/dev/null || true")
    time.sleep(1.0)


def run(config_path: str = "config.json", interactive: bool = True):
    if not MININET_AVAILABLE:
        print("Mininet is not available. Install Mininet and Open vSwitch on Linux.")
        sys.exit(1)

    config = load_config(config_path)
    os.makedirs("logs", exist_ok=True)
    setLogLevel("info")
    controller = config["controller"]
    controller_host = controller.get("of_host", "127.0.0.1")
    if controller_host in ("", "0.0.0.0"):
        controller_host = "127.0.0.1"

    topo = SDNLoadBalancerTopo(config)
    net = Mininet(
        topo=topo,
        switch=OVSSwitch,
        controller=None,
        autoSetMacs=False,
        autoStaticArp=False,
    )
    net.addController(
        "c0",
        controller=RemoteController,
        ip=controller_host,
        port=controller.get("of_port", 6653),
    )

    net.start()
    try:
        setup_control_network(net, config)
        if wait_for_switch(net):
            info("*** Switch connected to the controller\n")
        else:
            info("*** Warning: switch did not connect within 10 seconds\n")

        start_backend_processes(net, config)
        info("\n*** Network ready\n")
        info(f"*** VIP: {config['network']['vip']}:{config['network']['service_port']}\n")

        if not interactive:
            return net

        CLI(net)
    except Exception:
        if not interactive:
            net.stop()
            cleanup_control_network(config)
        raise
    finally:
        if interactive:
            net.stop()
            cleanup_control_network(config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mininet topology for the adaptive load balancer")
    parser.add_argument("--config", default="config.json", help="path to config.json")
    parser.add_argument("--non-interactive", action="store_true", help="start without the Mininet CLI")
    args = parser.parse_args()

    run(config_path=args.config, interactive=not args.non_interactive)


if __name__ == "__main__":
    main()
