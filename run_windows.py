from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser

from client.load_generator import LoadGenerator
from scenarios.testbed import SDNTestbed
from visualization.terminal_animation import play_animation

os.system("")

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_CYAN = "\033[96m"


def print_banner() -> None:
    print(f"\n{C_BLUE}{C_BOLD}{'=' * 72}{C_RESET}")
    print(f"{C_CYAN}{C_BOLD}   SDN-BASED ADAPTIVE LOAD BALANCER - WINDOWS CONTROL CENTER       {C_RESET}")
    print(f"{C_BLUE}{C_BOLD}{'=' * 72}{C_RESET}")
    print(" 1) Start Live SDN Load Balancer (auto-selected local port)")
    print(" 2) Run All 6 Demonstration Scenarios (Automated Suite)")
    print(" 3) Send Benchmark Traffic Through a Temporary Load Balancer")
    print(" 4) Play Terminal Visual Animation in Windows Terminal")
    print(" 5) Open Interactive HTML5 Animation in Browser")
    print(" 6) Re-render Animation GIF (sdn_load_balancer_animation.gif)")
    print(" 7) Run Unit Tests (pytest)")
    print(" 8) Run Hard Scenario (Overload h2 + Kill h3 Mid-Run)")
    print(" q) Exit")
    print(f"{C_BLUE}{'-' * 72}{C_RESET}")


def run_live_load_balancer() -> None:
    print(f"\n{C_GREEN}{C_BOLD}>>> Starting live SDN load balancer <<< {C_RESET}")

    testbed = SDNTestbed(mode="adaptive")
    testbed.start()
    print(f"Virtual service listening on {testbed.vip}:{testbed.vip_port}")
    for server_id, server in testbed.servers.items():
        print(
            f"Backend {server_id}: service {server.ip}:{server.service_port}, "
            f"telemetry {server.telemetry_ip}:{server.telemetry_port}"
        )
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(2.0)
            print(f"[{time.strftime('%H:%M:%S')}] Routing snapshot:")
            for server_id, status in testbed.engine.get_status_summary().items():
                print(
                    f"   {server_id}: latency={status['smoothed_latency_ms']} ms | "
                    f"connections={status['active_connections']} | "
                    f"score={status['composite_score']} | "
                    f"flows={status['total_flows_routed']}"
                )
    except KeyboardInterrupt:
        print("\nStopping load balancer")
    finally:
        testbed.stop()
        print("Load balancer stopped")


def run_scenarios() -> None:
    print(f"\n{C_CYAN}Running all 6 demonstration scenarios...{C_RESET}")
    subprocess.run([sys.executable, "-m", "scenarios.run_all_scenarios"])


def run_traffic() -> None:
    requests_input = input("Enter number of requests (default 60): ").strip()
    num_requests = int(requests_input) if requests_input.isdigit() else 60
    concurrency_input = input("Enter concurrency (default 10): ").strip()
    concurrency = int(concurrency_input) if concurrency_input.isdigit() else 10

    testbed = SDNTestbed(mode="adaptive")
    testbed.start()
    try:
        print(f"\nSending {num_requests} requests to {testbed.vip}:{testbed.vip_port}")
        generator = LoadGenerator(vip=testbed.vip, port=testbed.vip_port, concurrency=concurrency)
        generator.run_benchmark(num_requests=num_requests).print_report()
    finally:
        testbed.stop()


def open_browser_animation() -> None:
    html_path = os.path.abspath(os.path.join("visualization", "animation.html"))
    print(f"\nOpening {html_path} in the default browser...")
    webbrowser.open(f"file:///{html_path}")


def render_gif() -> None:
    print("\nRendering animation GIF with Pillow...")
    subprocess.run([sys.executable, "-m", "visualization.generate_animation_gif"])


def run_tests() -> None:
    print("\nRunning unit tests with pytest...")
    subprocess.run([sys.executable, "-m", "pytest", "-v"])


def main() -> None:
    while True:
        print_banner()
        choice = input(" Select option [1-8, q]: ").strip()

        if choice == "1":
            run_live_load_balancer()
        elif choice == "2":
            run_scenarios()
        elif choice == "3":
            run_traffic()
        elif choice == "4":
            play_animation(interactive=False)
            input(f"\n{C_YELLOW}Animation complete. Press Enter to return to the menu...{C_RESET}")
        elif choice == "5":
            open_browser_animation()
        elif choice == "6":
            render_gif()
        elif choice == "7":
            run_tests()
        elif choice == "8":
            print(f"\n{C_CYAN}Running hard scenario...{C_RESET}")
            subprocess.run([sys.executable, "-m", "scenarios.scenario6_hard"])
        elif choice.lower() == "q":
            print("Exiting.")
            break
        else:
            print("Invalid option, please retry.")


if __name__ == "__main__":
    main()
