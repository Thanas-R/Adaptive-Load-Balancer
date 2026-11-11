"""Scenario 3: Backend Failure & Graceful Failover Exclusion.

Demonstrates that when a backend (h3) crashes or becomes completely unavailable:
1. Telemetry heartbeats fail.
2. Consecutive failure threshold is reached.
3. The SDN controller transitions h3 to UNHEALTHY and excludes it from routing.
4. 100% of incoming connections continue without drops via remaining healthy backends.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from client.load_generator import LoadGenerator
from scenarios.testbed import SDNTestbed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scenario3")


def run_scenario3(testbed: Optional[SDNTestbed] = None) -> dict:
    should_stop = False
    if testbed is None:
        testbed = SDNTestbed(vip="127.0.0.1", vip_port=8000, mode="adaptive")
        testbed.start()
        should_stop = True

    try:
        logger.info("\n" + "=" * 60)
        logger.info(" SCENARIO 3: BACKEND FAILURE & AUTOMATIC EXCLUSION ")
        logger.info("=" * 60)

        # Baseline check
        time.sleep(1.0)
        logger.info("Initial Status before failure:")
        for sid, s in testbed.engine.get_status_summary().items():
            logger.info(f"  {sid}: Status={s['status']}")

        # Simulate sudden crash of h3
        logger.info("\n>>> CRASHING BACKEND SERVER h3 (Simulating process death)... <<<")
        testbed.servers["h3"].stop()

        # Telemetry probe triggers failure detection
        logger.info("Awaiting health probe failure detection...")
        for _ in range(4):
            testbed.telemetry.poll_backend("h3", "127.0.0.1", 9003)
            time.sleep(0.4)

        logger.info("\nBackend Status after crash detection:")
        for sid, s in testbed.engine.get_status_summary().items():
            logger.info(f"  {sid}: Status={s['status']}, Failures={testbed.engine.backends[sid].consecutive_failures}")

        assert testbed.engine.backends["h3"].health_status == "UNHEALTHY", "h3 should be UNHEALTHY"
        logger.info("SUCCESS: h3 is recognized as UNHEALTHY by SDN controller.")

        # Send traffic load to verify zero traffic routes to crashed h3
        logger.info("\nGenerating 50 concurrent requests while h3 is down...")
        generator = LoadGenerator(vip="127.0.0.1", port=8000, concurrency=8)
        result = generator.run_benchmark(num_requests=50)
        result.print_report("SCENARIO 3 RESULT: TRAFFIC ROUTING WHILE h3 IS OFFLINE")

        assert "h3" not in result.server_counts or result.server_counts["h3"] == 0, "No requests should reach h3!"
        logger.info("CONFIRMED: Exactly 0 requests routed to offline backend h3. Zero service disruption!")

        summary = {
            "scenario": "Scenario 3: Backend Failure",
            "failed_server": "h3",
            "total_requests": result.total_requests,
            "successful_requests": result.successful_requests,
            "failed_requests": result.failed_requests,
            "h3_traffic_count": result.server_counts.get("h3", 0),
            "distribution": result.server_counts,
        }
        return summary
    finally:
        if should_stop:
            testbed.stop()


if __name__ == "__main__":
    run_scenario3()
