from __future__ import annotations

import logging
import time
from typing import Optional

from client.load_generator import LoadGenerator
from scenarios.testbed import SDNTestbed

logger = logging.getLogger("scenario2")


def run_scenario2(testbed: Optional[SDNTestbed] = None) -> dict:
    should_stop = False
    if testbed is None:
        testbed = SDNTestbed(mode="adaptive")
        testbed.start()
        should_stop = True

    try:
        logger.info("SCENARIO 2: BACKEND SLOWDOWN & ADAPTIVE TRAFFIC STEERING")
        time.sleep(1.0)

        logger.info("Baseline metrics before slowdown:")
        for server_id, status in testbed.engine.get_status_summary().items():
            logger.info(
                "  %s: latency=%.2f ms, score=%.1f",
                server_id,
                status["smoothed_latency_ms"],
                status["composite_score"],
            )

        logger.info("Injecting 200 ms processing delay on backend h2")
        testbed.servers["h2"].set_processing_delay(200.0)

        testbed.warm_backend("h2", count=5)
        for _ in range(3):
            testbed.poll_backend("h2")
            time.sleep(0.2)

        logger.info("Metrics after slowdown detected:")
        for server_id, status in testbed.engine.get_status_summary().items():
            logger.info(
                "  %s: latency=%.2f ms, score=%.1f, status=%s",
                server_id,
                status["smoothed_latency_ms"],
                status["composite_score"],
                status["status"],
            )

        generator = LoadGenerator(vip=testbed.vip, port=testbed.vip_port, concurrency=10)
        result = generator.run_benchmark(num_requests=60)
        result.print_report("SCENARIO 2 RESULT: ADAPTIVE STEERING AWAY FROM SLOW h2")

        h2_share = (
            result.server_counts.get("h2", 0) / max(1, result.successful_requests)
        ) * 100.0
        logger.info(
            "Traffic received by slow h2: %s (%.1f%%)",
            result.server_counts.get("h2", 0),
            h2_share,
        )

        testbed.servers["h2"].set_processing_delay(20.0)
        testbed.warm_backend("h2", count=10)
        testbed.refresh_telemetry()

        summary = {
            "scenario": "Scenario 2: Backend Slowdown",
            "slowed_server": "h2",
            "total_requests": result.total_requests,
            "successful_requests": result.successful_requests,
            "failed_requests": result.failed_requests,
            "avg_latency_ms": round(result.avg_latency_ms, 2),
            "h2_share_pct": round(h2_share, 1),
            "distribution": result.server_counts,
        }
        return summary
    finally:
        if should_stop:
            testbed.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_scenario2()
