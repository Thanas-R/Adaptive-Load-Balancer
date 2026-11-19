from __future__ import annotations

import logging
import time
from typing import Optional

from client.load_generator import LoadGenerator
from scenarios.testbed import SDNTestbed

logger = logging.getLogger("scenario1")


def run_scenario1(testbed: Optional[SDNTestbed] = None) -> dict:
    should_stop = False
    if testbed is None:
        testbed = SDNTestbed(mode="adaptive")
        testbed.start()
        should_stop = True

    try:
        logger.info("SCENARIO 1: NORMAL BALANCED TRAFFIC (h2, h3, h4 HEALTHY)")
        time.sleep(1.0)

        logger.info("Initial backend status:")
        for server_id, status in testbed.engine.get_status_summary().items():
            logger.info(
                "  %s: status=%s, latency=%.2f ms, score=%.1f",
                server_id,
                status["status"],
                status["smoothed_latency_ms"],
                status["composite_score"],
            )

        generator = LoadGenerator(vip=testbed.vip, port=testbed.vip_port, concurrency=10)
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_scenario1()
