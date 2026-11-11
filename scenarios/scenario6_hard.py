"""Scenario 6: Hard Scenario - Server Overload + Mid-Run Server Kill.

College Project Requirement 9:
"Hard scenario: overload one server with heavy requests, then kill a server
mid-run. Traffic is redistributed and clients keep being served."

Step-by-step Execution:
1. Baseline: h2, h3, h4 are all healthy and receiving requests.
2. Overload phase: h2 is overwhelmed with heavy processing load (delay=250ms).
3. Controller detects degradation; score spikes; flows shift away from h2 to h3 & h4.
4. Sudden Crash phase: Mid-run, h3 is killed ungracefully (process terminated).
5. Telemetry probes fail; h3 is marked UNHEALTHY and excluded from OpenFlow routing.
6. Traffic dynamically redistributes to surviving healthy nodes without dropping clients.
7. System achieves resilience with verified per-server flow metrics.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional

from client.load_generator import BenchmarkResult, LoadGenerator
from scenarios.testbed import SDNTestbed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scenario6_hard")


def run_scenario6(testbed: Optional[SDNTestbed] = None) -> Dict[str, any]:
    should_stop = False
    if testbed is None:
        testbed = SDNTestbed(vip="127.0.0.1", vip_port=8000, mode="adaptive")
        testbed.start()
        should_stop = True

    try:
        logger.info("\n" + "=" * 70)
        logger.info(" SCENARIO 6: HARD TEST - OVERLOAD h2 + KILL h3 MID-RUN ")
        logger.info("=" * 70)

        # -------------------------------------------------------------
        # STEP 1: Baseline Health Check
        # -------------------------------------------------------------
        logger.info("\n[STEP 1] Verifying all 3 backends are healthy...")
        time.sleep(1.0)
        for sid, s in testbed.engine.get_status_summary().items():
            logger.info(f"  {sid}: status={s['status']}, latency={s['smoothed_latency_ms']}ms, score={s['composite_score']}")

        # -------------------------------------------------------------
        # STEP 2: Overload h2 with heavy processing delay
        # -------------------------------------------------------------
        logger.info("\n[STEP 2] Overloading server h2 with heavy requests (delay=250ms)...")
        testbed.servers["h2"].set_processing_delay(250.0)

        # Trigger telemetry poll so controller detects high load on h2
        for _ in range(3):
            testbed.telemetry.poll_backend("h2", "127.0.0.1", 9002)
            time.sleep(0.4)

        logger.info("Telemetry updated. Current engine scores:")
        for sid, s in testbed.engine.get_status_summary().items():
            logger.info(f"  {sid}: latency={s['smoothed_latency_ms']}ms, score={s['composite_score']}")

        # -------------------------------------------------------------
        # STEP 3: Launch concurrent traffic stream
        # -------------------------------------------------------------
        total_requests = 90
        concurrency = 8
        logger.info(f"\n[STEP 3] Launching {total_requests} concurrent requests...")

        generator = LoadGenerator(vip="127.0.0.1", port=8000, concurrency=concurrency)

        # Run generator in separate thread so we can kill h3 mid-run
        bench_result: Dict[str, Optional[BenchmarkResult]] = {"result": None}

        def worker():
            bench_result["result"] = generator.run_benchmark(num_requests=total_requests)

        t_load = threading.Thread(target=worker, daemon=True)
        t_load.start()

        # Let requests start flowing
        time.sleep(1.0)

        # -------------------------------------------------------------
        # STEP 4: Mid-run kill: Kill h3 ungracefully!
        # -------------------------------------------------------------
        logger.info("\n>>> [STEP 4] MID-RUN EVENT: KILLING SERVER h3 UNGRACEFULLY! <<<")
        testbed.servers["h3"].stop()

        # Controller probe fails 3 times -> mark UNHEALTHY
        for _ in range(4):
            testbed.telemetry.poll_backend("h3", "127.0.0.1", 9003)
            time.sleep(0.3)

        logger.info(f"h3 status is now: {testbed.engine.backends['h3'].health_status}")
        assert testbed.engine.backends["h3"].health_status == "UNHEALTHY", "h3 must be UNHEALTHY"

        # Wait for client thread to complete
        t_load.join(timeout=30.0)
        res = bench_result["result"]
        assert res is not None, "Benchmark result should be populated"

        # -------------------------------------------------------------
        # STEP 5: Verification and Distribution
        # -------------------------------------------------------------
        logger.info("\n[STEP 5] Workload completed under double failure/overload stress.")
        res.print_report("HARD SCENARIO (OVERLOAD h2 + KILL h3 MID-RUN)")

        # Count requests received by each backend
        counts = res.server_counts
        logger.info(f"Final per-server request counts: {counts}")

        # Assertions
        logger.info("Verifying resilience:")
        logger.info(f"  - Total successful requests: {res.successful_requests}/{total_requests}")
        logger.info(f"  - Server traffic distribution: {counts}")

        assert res.successful_requests == total_requests, "All requests should succeed"

        return {
            "success": True,
            "counts": counts,
            "throughput_rps": res.throughput_rps,
            "avg_latency_ms": res.avg_latency_ms,
            "p95_latency_ms": res.p95_latency_ms,
            "failed_requests": res.failed_requests,
        }

    finally:
        if should_stop:
            testbed.stop()


if __name__ == "__main__":
    run_scenario6()
