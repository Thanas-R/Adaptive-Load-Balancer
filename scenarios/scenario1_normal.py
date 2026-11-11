"""Scenario 1: Normal Traffic Distribution Across Healthy Servers.

Demonstrates that under uniform server capacity and low load,
traffic is evenly distributed across all healthy backends (h2, h3, h4).
"""

from __future__ import annotations

import logging
import time

from client.load_generator import LoadGenerator
from scenarios.testbed import SDNTestbed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scenario1")


def run_scenario1(testbed: Optional[SDNTestbed] = None) -> dict:
    should_stop = False
    if testbed is None:
        testbed = SDNTestbed(vip="127.0.0.1", vip_port=8000, mode="adaptive")
        testbed.start()
        should_stop = True

    try:
        logger.info("\n" + "=" * 60)
        logger.info(" SCENARIO 1: NORMAL BALANCED TRAFFIC (h2, h3, h4 HEALTHY) ")
        logger.info("=" * 60)

        # Allow initial telemetry probes to register
        time.sleep(1.0)
        logger.info("Initial Backend Status:")
        for sid, status in testbed.engine.get_status_summary().items():
            logger.info(f"  {sid}: status={status['status']}, latency={status['smoothed_latency_ms']}ms, score={status['composite_score']}")

        # Send concurrent load
        generator = LoadGenerator(vip="127.0.0.1", port=8000, concurrency=10)
        result = generator.run_benchmark(num_requests=60)
        result.print_report("SCENARIO 1 RESULT: NORMAL HEALTHY TRAFFIC")

        summary = {
            "scenario": "Scenario 1: Normal Traffic",
            "total_requests": result.total_requests,
            "successful_requests": result.successful_requests,
            "failed_requests": result.failed_requests,
            "avg_latency_ms": round(result.avg_latency_ms, 2),
            "p95_latency_ms": round(result.p95_latency_ms, 2),
            "distribution": result.server_counts,
        }
        return summary
    finally:
        if should_stop:
            testbed.stop()


if __name__ == "__main__":
    run_scenario1()
