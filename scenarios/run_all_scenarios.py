"""Master Scenario Runner.

Executes all 5 demonstration scenarios sequentially:
1. Normal traffic across healthy servers
2. Backend slowdown and adaptive avoidance
3. Backend crash and complete exclusion
4. Backend recovery and probationary reintegration
5. Comparative benchmark: Adaptive vs. Round-Robin

Generates persistent logs in logs/ directory.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

from scenarios.scenario1_normal import run_scenario1
from scenarios.scenario2_slowdown import run_scenario2
from scenarios.scenario3_failure import run_scenario3
from scenarios.scenario4_recovery import run_scenario4
from scenarios.scenario5_benchmark import run_scenario5
from scenarios.scenario6_hard import run_scenario6
from scenarios.testbed import SDNTestbed

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/all_scenarios.log", mode="w"),
    ],
)
logger = logging.getLogger("scenario_runner")


def main():
    logger.info("************************************************************")
    logger.info("  SDN ADAPTIVE LOAD BALANCER - DEMONSTRATION SCENARIOS TEST ")
    logger.info("************************************************************")

    # Start a unified testbed for Scenarios 1 - 4
    testbed = SDNTestbed(vip="127.0.0.1", vip_port=8000, mode="adaptive")
    testbed.start()

    results = {}
    try:
        # Scenario 1
        res1 = run_scenario1(testbed)
        results["scenario1"] = res1
        time.sleep(1.0)

        # Scenario 2
        res2 = run_scenario2(testbed)
        results["scenario2"] = res2
        time.sleep(1.0)

        # Scenario 3
        res3 = run_scenario3(testbed)
        results["scenario3"] = res3
        time.sleep(1.0)

        # Scenario 4
        res4 = run_scenario4(testbed)
        results["scenario4"] = res4
        time.sleep(1.0)

    finally:
        testbed.stop()

    # Scenario 5 (Runs separate testbeds for RR vs Adaptive)
    time.sleep(1.0)
    rr_res, adapt_res = run_scenario5()
    results["scenario5"] = {
        "round_robin": {
            "throughput_rps": round(rr_res.throughput_rps, 2),
            "avg_latency_ms": round(rr_res.avg_latency_ms, 2),
            "p95_latency_ms": round(rr_res.p95_latency_ms, 2),
            "distribution": rr_res.server_counts,
        },
        "adaptive": {
            "throughput_rps": round(adapt_res.throughput_rps, 2),
            "avg_latency_ms": round(adapt_res.avg_latency_ms, 2),
            "p95_latency_ms": round(adapt_res.p95_latency_ms, 2),
            "distribution": adapt_res.server_counts,
        },
    }

    # Scenario 6: Hard Scenario (Overload + Kill Mid-Run)
    time.sleep(1.0)
    res6 = run_scenario6()
    results["scenario6"] = res6

    # Save results to JSON
    with open("logs/scenario_results.json", "w") as f:
        json.dump(results, f, indent=2)

    logger.info("\nALL 6 SCENARIOS COMPLETED SUCCESSFULLY.")
    logger.info("Detailed logs saved to logs/all_scenarios.log and logs/scenario_results.json")


if __name__ == "__main__":
    main()
