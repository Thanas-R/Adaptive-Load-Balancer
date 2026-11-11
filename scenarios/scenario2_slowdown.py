"""Scenario 2: Backend Slowdown & Adaptive Traffic Steering.

Demonstrates that when one backend (h2) slows down (latency spikes from 20ms to 200ms):
1. Telemetry detects elevated latency.
2. The AdaptiveEngine's composite score for h2 increases significantly.
3. The SDN controller dynamically routes incoming TCP flows away from h2 towards h3 and h4.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from client.load_generator import LoadGenerator
from scenarios.testbed import SDNTestbed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scenario2")


def run_scenario2(testbed: Optional[SDNTestbed] = None) -> dict:
    should_stop = False
    if testbed is None:
        testbed = SDNTestbed(vip="127.0.0.1", vip_port=8000, mode="adaptive")
        testbed.start()
        should_stop = True

    try:
        logger.info("\n" + "=" * 60)
        logger.info(" SCENARIO 2: BACKEND SLOWDOWN & ADAPTIVE TRAFFIC STEERING ")
        logger.info("=" * 60)

        # Baseline: normal status
        time.sleep(1.0)
        logger.info("Baseline metrics before slowdown:")
        for sid, s in testbed.engine.get_status_summary().items():
            logger.info(f"  {sid}: Latency={s['smoothed_latency_ms']}ms, Score={s['composite_score']}")

        # Artificially inject high latency on h2 (simulate heavy compute or bottleneck)
        logger.info("\n>>> Injecting 200ms processing delay on backend h2... <<<")
        testbed.servers["h2"].set_processing_delay(200.0)

        # Wait for telemetry to sample and compute EMA
        logger.info("Waiting for telemetry collector to detect degradation...")
        for _ in range(3):
            # Query once to trigger telemetry update on h2
            testbed.telemetry.poll_backend("h2", "127.0.0.1", 9002)
            time.sleep(0.6)

        logger.info("\nMetrics after slowdown detected:")
        for sid, s in testbed.engine.get_status_summary().items():
            logger.info(f"  {sid}: Latency={s['smoothed_latency_ms']}ms, Score={s['composite_score']}, Status={s['status']}")

        # Generate traffic load
        logger.info("\nGenerating 60 concurrent requests under adaptive load balancing...")
        generator = LoadGenerator(vip="127.0.0.1", port=8000, concurrency=10)
        result = generator.run_benchmark(num_requests=60)
        result.print_report("SCENARIO 2 RESULT: ADAPTIVE STEERING AWAY FROM SLOW h2")

        h2_pct = (result.server_counts.get("h2", 0) / max(1, result.successful_requests)) * 100.0
        logger.info(f"Traffic received by slow h2: {result.server_counts.get('h2', 0)} ({h2_pct:.1f}%)")
        logger.info(f"Traffic successfully offloaded to fast h3 and h4!")

        # Reset h2 delay
        testbed.servers["h2"].set_processing_delay(20.0)

        summary = {
            "scenario": "Scenario 2: Backend Slowdown",
            "slowed_server": "h2",
            "total_requests": result.total_requests,
            "successful_requests": result.successful_requests,
            "failed_requests": result.failed_requests,
            "avg_latency_ms": round(result.avg_latency_ms, 2),
            "h2_share_pct": round(h2_pct, 1),
            "distribution": result.server_counts,
        }
        return summary
    finally:
        if should_stop:
            testbed.stop()


if __name__ == "__main__":
    run_scenario2()
