from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from client.load_generator import BenchmarkResult, LoadGenerator
from scenarios.testbed import SDNTestbed

logger = logging.getLogger("scenario6_hard")


def run_scenario6(testbed: Optional[SDNTestbed] = None) -> Dict[str, Any]:
    should_stop = False
    if testbed is None:
        testbed = SDNTestbed(mode="adaptive")
        testbed.start()
        should_stop = True

    try:
        logger.info("SCENARIO 6: HARD TEST - OVERLOAD h2 + KILL h3 MID-RUN")

        logger.info("[1] Verifying all backends are healthy")
        time.sleep(0.5)
        for server_id, status in testbed.engine.get_status_summary().items():
            logger.info(
                "  %s: status=%s, latency=%.2f ms, score=%.1f",
                server_id,
                status["status"],
                status["smoothed_latency_ms"],
                status["composite_score"],
            )

        logger.info("[2] Overloading h2 with a 250 ms processing delay")
        testbed.servers["h2"].set_processing_delay(250.0)

        testbed.warm_backend("h2", count=5)
        for _ in range(3):
            testbed.poll_backend("h2")
            time.sleep(0.2)

        logger.info("Engine scores after overload:")
        for server_id, status in testbed.engine.get_status_summary().items():
            logger.info(
                "  %s: latency=%.2f ms, score=%.1f",
                server_id,
                status["smoothed_latency_ms"],
                status["composite_score"],
            )

        total_requests = 120
        concurrency = 8
        logger.info("[3] Starting %s requests at 40 req/s", total_requests)

        generator = LoadGenerator(vip=testbed.vip, port=testbed.vip_port, concurrency=concurrency)
        bench_result: Dict[str, Optional[BenchmarkResult]] = {"result": None}

        def worker() -> None:
            bench_result["result"] = generator.run_benchmark(
                num_requests=total_requests,
                rate_limit_rps=40.0,
            )

        load_thread = threading.Thread(target=worker, daemon=True)
        load_thread.start()

        time.sleep(1.0)

        logger.info("[4] Mid-run event: stopping h3")
        testbed.servers["h3"].stop()

        for _ in range(4):
            testbed.poll_backend("h3")
            time.sleep(0.3)

        logger.info("h3 status is now %s", testbed.engine.backends["h3"].health_status)
        assert testbed.engine.backends["h3"].health_status == "UNHEALTHY"

        load_thread.join(timeout=30.0)
        result = bench_result["result"]
        assert result is not None

        logger.info("[5] Workload completed under overload and mid-run failure")
        result.print_report("HARD SCENARIO (OVERLOAD h2 + KILL h3 MID-RUN)")

        logger.info("Per-server request counts: %s", result.server_counts)
        logger.info(
            "Successful requests: %s/%s",
            result.successful_requests,
            total_requests,
        )

        assert result.successful_requests >= total_requests - 1

        return {
            "success": True,
            "counts": result.server_counts,
            "throughput_rps": result.throughput_rps,
            "avg_latency_ms": result.avg_latency_ms,
            "p95_latency_ms": result.p95_latency_ms,
            "failed_requests": result.failed_requests,
        }
    finally:
        if should_stop:
            testbed.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_scenario6()
