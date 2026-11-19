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


def main() -> None:
    logger.info("SDN ADAPTIVE LOAD BALANCER - DEMONSTRATION SCENARIOS TEST")

    results = {}
    testbed = SDNTestbed(mode="adaptive")
    testbed.start()
    try:
        results["scenario1"] = run_scenario1(testbed)
        time.sleep(0.5)

        results["scenario2"] = run_scenario2(testbed)
        time.sleep(0.5)

        results["scenario3"] = run_scenario3(testbed)
        time.sleep(0.5)

        results["scenario4"] = run_scenario4(testbed)
        time.sleep(0.5)
    finally:
        testbed.stop()

    time.sleep(1.0)
    rr_result, adaptive_result = run_scenario5()
    results["scenario5"] = {
        "round_robin": {
            "throughput_rps": round(rr_result.throughput_rps, 2),
            "avg_latency_ms": round(rr_result.avg_latency_ms, 2),
            "p95_latency_ms": round(rr_result.p95_latency_ms, 2),
            "distribution": rr_result.server_counts,
        },
        "adaptive": {
            "throughput_rps": round(adaptive_result.throughput_rps, 2),
            "avg_latency_ms": round(adaptive_result.avg_latency_ms, 2),
            "p95_latency_ms": round(adaptive_result.p95_latency_ms, 2),
            "distribution": adaptive_result.server_counts,
        },
    }

    time.sleep(1.0)
    results["scenario6"] = run_scenario6()

    with open("logs/scenario_results.json", "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)

    logger.info("ALL 6 SCENARIOS COMPLETED SUCCESSFULLY")
    logger.info("Logs saved to logs/all_scenarios.log and logs/scenario_results.json")


if __name__ == "__main__":
    main()
