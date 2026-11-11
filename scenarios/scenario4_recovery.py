"""Scenario 4: Backend Recovery & Gradual Service Reintegration.

Demonstrates that when the failed backend (h3) is brought back online:
1. Telemetry detects heartbeats.
2. Server transitions from UNHEALTHY -> RECOVERING.
3. Controller applies recovery dampening (probationary warming).
4. After stability cooldown, h3 transitions back to HEALTHY and receives full traffic share.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from backend.server import BackendServer
from client.load_generator import LoadGenerator
from scenarios.testbed import SDNTestbed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scenario4")


def run_scenario4(testbed: Optional[SDNTestbed] = None) -> dict:
    should_stop = False
    if testbed is None:
        testbed = SDNTestbed(vip="127.0.0.1", vip_port=8000, mode="adaptive")
        testbed.start()
        should_stop = True

    try:
        logger.info("\n" + "=" * 60)
        logger.info(" SCENARIO 4: BACKEND RECOVERY & GRADUAL SERVICE REINTEGRATION ")
        logger.info("=" * 60)

        # 1. First ensure h3 is UNHEALTHY (or crash it if not already)
        if testbed.engine.backends["h3"].health_status != "UNHEALTHY":
            testbed.servers["h3"].stop()
            for _ in range(4):
                testbed.telemetry.poll_backend("h3", "127.0.0.1", 9003)
                time.sleep(0.3)

        logger.info(f"State before recovery: h3 Status = {testbed.engine.backends['h3'].health_status}")

        # 2. Restart h3 server process
        logger.info("\n>>> RESTARTING BACKEND SERVER h3... <<<")
        new_h3 = BackendServer(
            server_id="h3",
            ip="127.0.0.1",
            service_port=8003,
            telemetry_port=9003,
            processing_delay_ms=20.0,
        )
        new_h3.start()
        testbed.servers["h3"] = new_h3

        # 3. Telemetry probe detects recovery
        logger.info("Polling h3 telemetry to detect restart...")
        testbed.telemetry.poll_backend("h3", "127.0.0.1", 9003)
        time.sleep(0.5)

        logger.info(f"State immediately after recovery: h3 Status = {testbed.engine.backends['h3'].health_status}")
        assert testbed.engine.backends["h3"].health_status in ("RECOVERING", "HEALTHY")

        # 4. Generate probationary traffic during recovery phase
        logger.info("\nSending probationary traffic batch during RECOVERING cooldown...")
        generator = LoadGenerator(vip="127.0.0.1", port=8000, concurrency=8)
        probation_res = generator.run_benchmark(num_requests=30)
        logger.info(f"Traffic distribution during recovery: {probation_res.server_counts}")

        # 5. Wait for recovery cooldown (configured as 3.0s in testbed)
        logger.info("Waiting for recovery cooldown period to complete (3 seconds)...")
        time.sleep(3.2)
        testbed.telemetry.poll_backend("h3", "127.0.0.1", 9003)

        logger.info(f"State after recovery cooldown: h3 Status = {testbed.engine.backends['h3'].health_status}")
        assert testbed.engine.backends["h3"].health_status == "HEALTHY", "h3 should now be fully HEALTHY"

        # 6. Generate normal traffic to show full restoration
        logger.info("\nSending full traffic batch post-restoration...")
        full_res = generator.run_benchmark(num_requests=60)
        full_res.print_report("SCENARIO 4 RESULT: FULL RESTORATION ACROSS ALL 3 BACKENDS")

        assert "h3" in full_res.server_counts and full_res.server_counts["h3"] > 0
        logger.info("SUCCESS: Backend h3 is fully restored and handling its proportional traffic share!")

        summary = {
            "scenario": "Scenario 4: Backend Recovery",
            "recovered_server": "h3",
            "final_status": testbed.engine.backends["h3"].health_status,
            "post_recovery_distribution": full_res.server_counts,
        }
        return summary
    finally:
        if should_stop:
            testbed.stop()


if __name__ == "__main__":
    run_scenario4()
