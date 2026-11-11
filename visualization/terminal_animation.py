"""Terminal Visual Animation for SDN Adaptive Load Balancer.

Plays a live, interactive, colorized animation in Windows Terminal / PowerShell.
Showcases:
1. Network topology & virtual IP
2. Telemetry polling & adaptive scoring
3. OpenFlow 1.3 PacketIn, FlowMod NAT rewriting, and line-rate forwarding
4. Degradation and crash failover
5. Benchmark comparison with Round-Robin
"""

import os
import sys
import time

# Enable ANSI colors on Windows
os.system("")

# ANSI Color codes
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_RED = "\033[91m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_MAGENTA = "\033[95m"
C_CYAN = "\033[96m"
C_WHITE = "\033[97m"
C_BG_BLUE = "\033[44m"
C_DIM = "\033[2m"


def clear_screen():
    print("\033[2J\033[H", end="")


def draw_header(stage_title: str):
    print(f"{C_BG_BLUE}{C_WHITE}{C_BOLD}  SDN-BASED ADAPTIVE LOAD BALANCER - VISUAL DEMONSTRATION  {C_RESET}")
    print(f"{C_CYAN}{C_BOLD} Stage: {stage_title}{C_RESET}")
    print(f"{C_DIM}{'=' * 75}{C_RESET}")


def render_scene(
    stage_title: str,
    client_pkt: str = "       ",
    s1_status: str = "IDLE",
    ctrl_msg: str = "",
    h2_state: str = "20ms (Score: 0.00)",
    h3_state: str = "20ms (Score: 0.00)",
    h4_state: str = "20ms (Score: 0.00)",
    h2_pkt: str = "       ",
    h3_pkt: str = "       ",
    h4_pkt: str = "       ",
    h3_color: str = C_GREEN,
    info_box: str = "",
):
    clear_screen()
    draw_header(stage_title)

    # Controller Block
    print(f"                       {C_BLUE}+-----------------------------------+{C_RESET}")
    print(f"                       {C_BLUE}|{C_RESET} {C_BOLD}SDN Controller (OF 1.3 + Engine){C_RESET}  {C_BLUE}|{C_RESET}")
    ctrl_display = f"{ctrl_msg[:33]:<33}"
    print(f"                       {C_BLUE}|{C_RESET} {C_YELLOW}{ctrl_display}{C_RESET} {C_BLUE}|{C_RESET}")
    print(f"                       {C_BLUE}+-----------------+-----------------+{C_RESET}")
    print(f"                                         | Control (TCP 6653)")
    print(f"                                         v")

    # Topology Line
    print(f"   {C_GREEN}+---------------+{C_RESET}              {C_CYAN}+-----------------+{C_RESET}              {C_YELLOW}+-----------------------+{C_RESET}")
    print(f"   {C_GREEN}|   Client h1   |{C_RESET} {client_pkt} {C_CYAN}| Open vSwitch s1 |{C_RESET} {h2_pkt} {C_YELLOW}| Backend h2 (10.0.0.2) |{C_RESET}")
    print(f"   {C_GREEN}|   10.0.0.1    |{C_RESET} ===========> {C_CYAN}| VIP: 10.0.0.100 |{C_RESET} ===========> {C_YELLOW}| {h2_state:<21} |{C_RESET}")
    print(f"   {C_GREEN}+---------------+{C_RESET}              {C_CYAN}| Status: {s1_status:<7} |{C_RESET}              {C_YELLOW}+-----------------------+{C_RESET}")
    print(f"                                  {C_CYAN}+--------+--------+{C_RESET}")
    print(f"                                           |")
    print(f"                                           +-- {h3_pkt} ---> {h3_color}+-----------------------+{C_RESET}")
    print(f"                                           |                    {h3_color}| Backend h3 (10.0.0.3) |{C_RESET}")
    print(f"                                           |                    {h3_color}| {h3_state:<21} |{C_RESET}")
    print(f"                                           |                    {h3_color}+-----------------------+{C_RESET}")
    print(f"                                           +-- {h4_pkt} ---> {C_MAGENTA}+-----------------------+{C_RESET}")
    print(f"                                                                {C_MAGENTA}| Backend h4 (10.0.0.4) |{C_RESET}")
    print(f"                                                                {C_MAGENTA}| {h4_state:<21} |{C_RESET}")
    print(f"                                                                {C_MAGENTA}+-----------------------+{C_RESET}")
    print(f"{C_DIM}{'-' * 75}{C_RESET}")
    if info_box:
        print(f"{C_WHITE}{info_box}{C_RESET}")
    print(f"{C_DIM}{'=' * 75}{C_RESET}")


def play_animation(interactive: bool = False):
    def step(sec: float = 0.5):
        if interactive:
            input(f"{C_YELLOW}[Press ENTER to advance...]{C_RESET}")
        else:
            time.sleep(sec)

    # 1. Initialization
    render_scene(
        "1. Network Ready (All Nodes Healthy)",
        info_box="Switch s1 connected to SDN Controller. Backends h2, h3, h4 healthy at 20ms baseline.",
    )
    step(1.5)

    # 2. Telemetry Polling
    render_scene(
        "2. Telemetry Heartbeat Polling",
        ctrl_msg="Polling backends over TCP...",
        info_box="Controller queries telemetry ports (9002, 9003, 9004). All backends report HEALTHY (Score=0.0).",
    )
    step(1.2)

    # 3. Client Sends TCP SYN
    pkt_anim = [
        (">>SYN>>", "       ", "       ", "       "),
        ("==SYN==", "       ", "       ", "       "),
        ("       ", "       ", "       ", "       "),
    ]
    for p_c, p_2, p_3, p_4 in pkt_anim:
        render_scene(
            "3. Client Initiates TCP Connection",
            client_pkt=f"{C_GREEN}{p_c}{C_RESET}",
            s1_status="PKT-IN",
            ctrl_msg="New flow arriving at switch",
            info_box="Client h1 sends TCP SYN to Virtual IP 10.0.0.100:8000. Switch s1 intercepts initial packet.",
        )
        time.sleep(0.4)

    # 4. OpenFlow PacketIn & FlowMod Installation
    render_scene(
        "4. Controller Computes Score & Installs FlowMod",
        s1_status="OF-MOD",
        ctrl_msg="Selected: h2 (Score: 0.00)",
        info_box=(
            "Controller evaluates composite score: 0.50*C + 0.35*L + 0.15*E.\n"
            "Installs bi-directional NAT FlowMod on s1: set_dst_ip=10.0.0.2, out_port=2."
        ),
    )
    step(1.5)

    # 5. Rewritten Packet reaches h2
    render_scene(
        "5. Direct Hardware Forwarding to h2",
        s1_status="ACTIVE",
        ctrl_msg="Flow installed (Idle timeout 30s)",
        h2_pkt=f"{C_GREEN}>>DATA>>{C_RESET}",
        h2_state="Conns: 1 | 20.2ms",
        info_box="Packet destination rewritten to 10.0.0.2. Subsequent data packets bypass controller line-rate!",
    )
    step(1.5)

    # 6. Degradation Scenario (h2 slows down)
    render_scene(
        "6. Backend h2 Degradation (Latency Spikes to 200ms)",
        ctrl_msg="Telemetry: h2 latency spike!",
        h2_state=f"{C_RED}200ms (Score: 0.73){C_RESET}",
        h3_state="20ms (Score: 0.00)",
        h4_state="20ms (Score: 0.00)",
        info_box="Backend h2 experiences high load. Latency spikes to 200ms. Telemetry reports new latency to controller.",
    )
    step(1.8)

    # 7. Adaptive Steering to h4
    render_scene(
        "7. Adaptive Steering: Diverting to Fast Node h4",
        client_pkt=f"{C_CYAN}>>SYN>>{C_RESET}",
        s1_status="ADAPT",
        ctrl_msg="Steered: h4 (Score: 0.00)",
        h2_state=f"{C_RED}200ms (Score: 0.73){C_RESET}",
        h4_pkt=f"{C_CYAN}>>DATA>>{C_RESET}",
        info_box="Controller avoids overloaded h2 (score 0.73). Dynamically routes incoming connections to fast node h4!",
    )
    step(1.8)

    # 8. Server Crash & Automatic Failover
    render_scene(
        "8. Backend Failure: h3 Crashes",
        ctrl_msg=f"{C_RED}h3 UNHEALTHY (3 failures){C_RESET}",
        h3_state=f"{C_RED}CRASHED / OFFLINE{C_RESET}",
        h3_color=C_RED,
        info_box="Backend h3 terminates. Telemetry probe times out 3 times. Controller marks h3 UNHEALTHY and excludes it.",
    )
    step(1.8)

    # 9. Zero-Downtime Failover Routing
    render_scene(
        "9. Seamless Failover to Surviving Backends",
        client_pkt=f"{C_GREEN}>>SYN>>{C_RESET}",
        s1_status="FAILOVER",
        ctrl_msg="Routing only to {h2, h4}",
        h2_pkt=f"{C_GREEN}>>DATA>>{C_RESET}",
        h3_state=f"{C_RED}EXCLUDED{C_RESET}",
        h3_color=C_RED,
        info_box="100% of new connections routed exclusively across healthy servers. Exactly 0 dropped requests!",
    )
    step(1.8)

    # 10. Benchmark Comparison Display
    clear_screen()
    draw_header("10. Empirical Benchmark: Adaptive vs. Round-Robin")
    print(f"\n{C_BOLD}Heterogeneous Environment:{C_RESET} h2 (15ms fast), h3 (40ms medium), h4 (180ms overloaded)\n")
    print(f" {'Metric':<28} | {'Round-Robin (Baseline)':<22} | {'Adaptive SDN':<20} ")
    print(f" {'-' * 28} | {'-' * 22} | {'-' * 20} ")
    print(f" {'Throughput (req/s)':<28} | {'115.89 req/s':<22} | {C_GREEN}{'475.40 req/s (+310%)':<20}{C_RESET} ")
    print(f" {'Mean Latency (ms)':<28} | {'91.36 ms':<22} | {C_GREEN}{'22.31 ms (-75.6%)':<20}{C_RESET} ")
    print(f" {'95th Percentile (p95)':<28} | {'203.01 ms':<22} | {C_GREEN}{'38.75 ms (-80.9%)':<20}{C_RESET} ")
    print(f" {'Server Distribution':<28} | {'h2:33%, h3:34%, h4:33%':<22} | {C_GREEN}{'h2: 100% (Fast Node)':<20}{C_RESET} ")
    print(f"{C_DIM}{'=' * 75}{C_RESET}")
    print(f"\n{C_GREEN}{C_BOLD}>> Adaptive SDN eliminated head-of-line blocking and boosted throughput by 3.1x! <<{C_RESET}\n")


if __name__ == "__main__":
    interactive_mode = "--interactive" in sys.argv or "-i" in sys.argv
    play_animation(interactive=interactive_mode)
