from __future__ import annotations

import logging
import time
from typing import Optional

from client.load_generator import LoadGenerator
from scenarios.testbed import SDNTestbed

logger = logging.getLogger("scenario4")


def run_scenario4(testbed: Optional[SDNTestbed] = None) -> dict:
    should_stop = False
    if testbed is None:
        testbed = SDNTestbed(mode="adaptive")
        testbed.start()
        should_stop = True

    try:
        logger.info("SCENARIO 4: BACKEND RECOVERY & GRADUAL SERVICE REINTEGRATION")

        if testbed.engine.backends["h3"].health_status != "UNHEALTHY":
            logger.info("Taking h3 offline first")
            testbed.servers["h3"].stop()
            for _ in range(4):
                testbed.poll_backend("h3")
                time.sleep(0.3)

        logger.info("State before recovery: h3 status=%s", testbed.engine.backends["h3"].health_status)

        logger.info("Restarting backend h3")
        testbed.restart_backend("h3", delay_ms=20.0)

        testbed.poll_backend("h3")
        time.sleep(0.2)
        logger.info("State immediately after recovery: h3 status=%s", testbed.engine.backends["h3"].health_status)
        assert testbed.engine.backends["h3"].health_status in ("RECOVERING", "HEALTHY")

        generator = LoadGenerator(vip=testbed.vip, port=testbed.vip_port, concurrency=8)
        probation = generator.run_benchmark(num_requests=30)
        logger.info("Traffic distribution during recovery: %s", probation.server_counts)

        logger.info("Waiting for recovery cooldown")
        time.sleep(3.2)
        testbed.poll_backend("h3")

        logger.info("State after recovery cooldown: h3 status=%s", testbed.engine.backends["h3"].health_status)
        assert testbed.engine.backends["h3"].health_status == "HEALTHY"

        full_result = generator.run_benchmark(num_requests=60)
        full_result.print_report("SCENARIO 4 RESULT: FULL RESTORATION ACROSS ALL 3 BACKENDS")

        assert full_result.server_counts.get("h3", 0) > 0

        summary = {
            "scenario": "Scenario 4: Backend Recovery",
            "recovered_server": "h3",
            "final_status": testbed.engine.backends["h3"].health_status,
            "post_recovery_distribution": full_result.server_counts,
        }
        return summary
    finally:
        if should_stop:
            testbed.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_scenario4()
