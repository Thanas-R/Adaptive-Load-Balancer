from __future__ import annotations

import logging
import time
from typing import Tuple

from client.load_generator import BenchmarkResult, LoadGenerator
from scenarios.testbed import SDNTestbed

logger = logging.getLogger("scenario5")


def _prepare(testbed: SDNTestbed, delays: dict) -> None:
    for server_id, delay in delays.items():
        testbed.servers[server_id].set_processing_delay(delay)
        testbed.warm_backend(server_id, count=5)
    testbed.refresh_telemetry()


def run_scenario5() -> Tuple[BenchmarkResult, BenchmarkResult]:
    logger.info("SCENARIO 5: COMPARATIVE EVALUATION (ADAPTIVE VS ROUND-ROBIN)")
    delays = {"h2": 15.0, "h3": 40.0, "h4": 180.0}

    logger.info("[1/2] Initializing round-robin baseline")
    tb_rr = SDNTestbed(mode="round_robin")
    try:
        tb_rr.start()
        _prepare(tb_rr, delays)
        time.sleep(0.3)

        gen_rr = LoadGenerator(vip=tb_rr.vip, port=tb_rr.vip_port, concurrency=12)
        rr_result = gen_rr.run_benchmark(num_requests=100)
        rr_result.print_report("ROUND-ROBIN SCHEDULING RESULTS")
    finally:
        tb_rr.stop()

    time.sleep(1.0)

    logger.info("[2/2] Initializing adaptive scheduling")
    tb_adapt = SDNTestbed(mode="adaptive")
    try:
        tb_adapt.start()
        _prepare(tb_adapt, delays)

        logger.info("Adaptive engine scores before benchmark:")
        for server_id, status in tb_adapt.engine.get_status_summary().items():
            logger.info(
                "  %s: latency=%.2f ms, score=%.1f",
                server_id,
                status["smoothed_latency_ms"],
                status["composite_score"],
            )

        gen_adapt = LoadGenerator(vip=tb_adapt.vip, port=tb_adapt.vip_port, concurrency=12)
        adapt_result = gen_adapt.run_benchmark(num_requests=100)
        adapt_result.print_report("ADAPTIVE SDN LOAD BALANCING RESULTS")
    finally:
        tb_adapt.stop()

    sep = "=" * 76
    print(f"\n{sep}")
    print(f" {'COMPREHENSIVE PERFORMANCE COMPARISON SUMMARY'.center(74)} ")
    print(sep)
    print(f" {'Metric':<30} | {'Round-Robin (Baseline)':<18} | {'Adaptive SDN':<18} ")
    print("-" * 76)

    def print_row(label: str, rr_value: str, adaptive_value: str, improvement: str = "") -> None:
        suffix = f" ({improvement})" if improvement else ""
        print(f" {label:<30} | {rr_value:<18} | {adaptive_value:<18}{suffix}")

    print_row("Total Requests", str(rr_result.total_requests), str(adapt_result.total_requests))
    print_row("Successful Requests", str(rr_result.successful_requests), str(adapt_result.successful_requests))
    print_row("Failed Requests", str(rr_result.failed_requests), str(adapt_result.failed_requests))
    print_row("Test Duration (s)", f"{rr_result.duration_sec:.2f} s", f"{adapt_result.duration_sec:.2f} s")

    throughput_gain = (
        (adapt_result.throughput_rps - rr_result.throughput_rps)
        / max(0.1, rr_result.throughput_rps)
    ) * 100.0
    print_row(
        "Throughput (req/s)",
        f"{rr_result.throughput_rps:.2f}",
        f"{adapt_result.throughput_rps:.2f}",
        f"+{throughput_gain:.1f}%",
    )

    latency_gain = (
        (rr_result.avg_latency_ms - adapt_result.avg_latency_ms)
        / max(0.1, rr_result.avg_latency_ms)
    ) * 100.0
    print_row(
        "Mean Latency (ms)",
        f"{rr_result.avg_latency_ms:.2f} ms",
        f"{adapt_result.avg_latency_ms:.2f} ms",
        f"-{latency_gain:.1f}%",
    )

    p95_gain = (
        (rr_result.p95_latency_ms - adapt_result.p95_latency_ms)
        / max(0.1, rr_result.p95_latency_ms)
    ) * 100.0
    print_row(
        "95th Percentile (p95)",
        f"{rr_result.p95_latency_ms:.2f} ms",
        f"{adapt_result.p95_latency_ms:.2f} ms",
        f"-{p95_gain:.1f}%",
    )

    print("-" * 76)
    print(" Per-server connection distribution:")
    for label, server_id in (("h2 (15ms)", "h2"), ("h3 (40ms)", "h3"), ("h4 (180ms)", "h4")):
        rr_count = rr_result.server_counts.get(server_id, 0)
        adaptive_count = adapt_result.server_counts.get(server_id, 0)
        print(
            f"   {label:<28} | {rr_count:5d} requests "
            f"({rr_count / max(1, rr_result.successful_requests) * 100:4.1f}%) | "
            f"{adaptive_count:5d} requests "
            f"({adaptive_count / max(1, adapt_result.successful_requests) * 100:4.1f}%)"
        )
    print(f"{sep}\n")

    return rr_result, adapt_result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_scenario5()
