from __future__ import annotations

import logging
import time
from typing import Optional

from client.load_generator import LoadGenerator
from scenarios.testbed import SDNTestbed

logger = logging.getLogger("scenario3")


def run_scenario3(testbed: Optional[SDNTestbed] = None) -> dict:
    should_stop = False
    if testbed is None:
        testbed = SDNTestbed(mode="adaptive")
        testbed.start()
        should_stop = True

    try:
        logger.info("SCENARIO 3: BACKEND FAILURE & AUTOMATIC EXCLUSION")
        time.sleep(1.0)

        logger.info("Initial status before failure:")
        for server_id, status in testbed.engine.get_status_summary().items():
            logger.info("  %s: status=%s", server_id, status["status"])

        logger.info("Crashing backend h3")
        testbed.servers["h3"].stop()

        logger.info("Awaiting health probe failure detection")
        for _ in range(4):
            testbed.poll_backend("h3")
            time.sleep(0.3)

        logger.info("Backend status after crash detection:")
        for server_id, status in testbed.engine.get_status_summary().items():
            backend = testbed.engine.backends[server_id]
            logger.info(
                "  %s: status=%s, failures=%s",
                server_id,
                status["status"],
                backend.consecutive_failures,
            )

        assert testbed.engine.backends["h3"].health_status == "UNHEALTHY"

        generator = LoadGenerator(vip=testbed.vip, port=testbed.vip_port, concurrency=8)
        result = generator.run_benchmark(num_requests=50)
        result.print_report("SCENARIO 3 RESULT: TRAFFIC ROUTING WHILE h3 IS OFFLINE")

        assert result.server_counts.get("h3", 0) == 0

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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_scenario3()
