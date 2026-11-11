"""Windows Native Interactive Control Center.

Allows running the SDN Adaptive Load Balancer, executing scenarios,
testing live traffic, and viewing animations directly in Windows Terminal.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser

from client.load_generator import LoadGenerator
from scenarios.testbed import SDNTestbed
from visualization.terminal_animation import play_animation

# Enable ANSI colors on Windows
os.system("")

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_CYAN = "\033[96m"


def print_banner():
    print(f"\n{C_BLUE}{C_BOLD}{'=' * 72}{C_RESET}")
    print(f"{C_CYAN}{C_BOLD}   SDN-BASED ADAPTIVE LOAD BALANCER - WINDOWS CONTROL CENTER       {C_RESET}")
    print(f"{C_BLUE}{C_BOLD}{'=' * 72}{C_RESET}")
    print(" 1) Start Live SDN Load Balancer (Listens on 127.0.0.1:8000)")
    print(" 2) Run All 6 Demonstration Scenarios (Automated Suite)")
    print(" 3) Send Concurrent Benchmark Traffic (Load Generator)")
    print(" 4) Play Terminal Visual Animation in Windows Terminal")
    print(" 5) Open Interactive HTML5 Animation in Browser (60 FPS)")
    print(" 6) Re-render Animation GIF (sdn_load_balancer_animation.gif)")
    print(" 7) Run Unit Tests (12 pytest suites)")
    print(" 8) Run Hard Scenario (Overload h2 + Kill h3 Mid-Run)")
    print(" q) Exit")
    print(f"{C_BLUE}{'-' * 72}{C_RESET}")


def run_live_load_balancer():
    print(f"\n{C_GREEN}{C_BOLD}>>> Starting Live SDN Load Balancer on 127.0.0.1:8000 <<< {C_RESET}")
    print("Backends running: h2 (8002), h3 (8003), h4 (8004)")
    print("Telemetry active on ports 9002, 9003, 9004")
    print("Press Ctrl+C to stop the load balancer.\n")

    testbed = SDNTestbed(vip="127.0.0.1", vip_port=8000, mode="adaptive")
    testbed.start()

    try:
        while True:
            time.sleep(2.0)
            summary = testbed.engine.get_status_summary()
            print(f"[{time.strftime('%H:%M:%S')}] Active Routing Snapshot:")
            for sid, s in summary.items():
                print(f"   {sid}: Latency={s['smoothed_latency_ms']}ms | Conns={s['active_connections']} | Score={s['composite_score']} | Flows={s['total_flows_routed']}")
    except KeyboardInterrupt:
        print("\nStopping SDN Load Balancer...")
    finally:
        testbed.stop()
        print("SDN Load Balancer stopped cleanly.")


def run_scenarios():
    print(f"\n{C_CYAN}Running all 5 demonstration scenarios...{C_RESET}")
    subprocess.run([sys.executable, "-m", "scenarios.run_all_scenarios"])


def run_traffic():
    reqs = input("Enter number of requests (default 60): ").strip()
    num_reqs = int(reqs) if reqs.isdigit() else 60
    conns = input("Enter concurrency (default 10): ").strip()
    num_conns = int(conns) if conns.isdigit() else 10

    print(f"\nSending {num_reqs} requests with concurrency {num_conns} to 127.0.0.1:8000...")
    gen = LoadGenerator(vip="127.0.0.1", port=8000, concurrency=num_conns)
    res = gen.run_benchmark(num_requests=num_reqs)
    res.print_report()


def open_browser_animation():
    html_path = os.path.abspath(os.path.join("visualization", "animation.html"))
    print(f"\nOpening {html_path} in default browser...")
    webbrowser.open(f"file:///{html_path}")


def render_gif():
    print("\nRendering animation GIF with Pillow...")
    subprocess.run([sys.executable, "-m", "visualization.generate_animation_gif"])


def run_tests():
    print("\nRunning unit tests with pytest...")
    subprocess.run([sys.executable, "-m", "pytest", "-v"])


def main():
    while True:
        print_banner()
        choice = input(" Select option [1-7, q]: ").strip()
        if choice == "1":
            run_live_load_balancer()
        elif choice == "2":
            run_scenarios()
        elif choice == "3":
            run_traffic()
        elif choice == "4":
            play_animation(interactive=False)
            input(f"\n{C_YELLOW}Animation complete. Press Enter to return to menu...{C_RESET}")
        elif choice == "5":
            open_browser_animation()
        elif choice == "6":
            render_gif()
        elif choice == "7":
            run_tests()
        elif choice == "8":
            print(f"\n{C_CYAN}Running Scenario 6 (Hard Test: Overload + Kill Mid-Run)...{C_RESET}")
            subprocess.run([sys.executable, "-m", "scenarios.scenario6_hard"])
        elif choice.lower() == "q":
            print("Exiting.")
            break
        else:
            print("Invalid option, please retry.")


if __name__ == "__main__":
    main()
