"""Scenario 5: Comparative Benchmark: Adaptive Scheduling vs. Round-Robin.

Compares Adaptive SDN Load Balancing against static Round-Robin under
heterogeneous server processing latencies:
- h2: Fast node (15ms delay)
- h3: Moderate node (40ms delay)
- h4: Slow/Stressed node (180ms delay)

Evaluates:
- Total throughput (req/sec)
- Mean latency
- 95th percentile latency (p95)
- Failed requests
- Per-server traffic distribution
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Tuple

from client.load_generator import BenchmarkResult, LoadGenerator
from scenarios.testbed import SDNTestbed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scenario5")


def run_scenario5() -> Tuple[BenchmarkResult, BenchmarkResult]:
    logger.info("\n" + "=" * 68)
    logger.info(" SCENARIO 5: COMPARATIVE EVALUATION (ADAPTIVE VS ROUND-ROBIN) ")
    logger.info("=" * 68)

    # ---------------------------------------------------------
    # PART 1: ROUND-ROBIN SCHEDULING BASELINE
    # ---------------------------------------------------------
    logger.info("\n>>> [1/2] INITIALIZING TESTBED IN ROUND-ROBIN MODE... <<<")
    tb_rr = SDNTestbed(vip="127.0.0.1", vip_port=8000, mode="round_robin")
    tb_rr.start()

    # Set heterogeneous server processing latencies
    tb_rr.servers["h2"].set_processing_delay(15.0)
    tb_rr.servers["h3"].set_processing_delay(40.0)
    tb_rr.servers["h4"].set_processing_delay(180.0)

    time.sleep(1.0)
    logger.info("Executing 100 concurrent requests with Round-Robin scheduling...")
    gen_rr = LoadGenerator(vip="127.0.0.1", port=8000, concurrency=12)
    rr_result = gen_rr.run_benchmark(num_requests=100)
    rr_result.print_report("ROUND-ROBIN SCHEDULING RESULTS")
    tb_rr.stop()

    # ---------------------------------------------------------
    # PART 2: ADAPTIVE SDN LOAD BALANCING
    # ---------------------------------------------------------
    time.sleep(1.5)
    logger.info("\n>>> [2/2] INITIALIZING TESTBED IN ADAPTIVE SCHEDULING MODE... <<<")
    tb_adapt = SDNTestbed(vip="127.0.0.1", vip_port=8000, mode="adaptive")
    tb_adapt.start()

    # Set identical heterogeneous server processing latencies
    tb_adapt.servers["h2"].set_processing_delay(15.0)
    tb_adapt.servers["h3"].set_processing_delay(40.0)
    tb_adapt.servers["h4"].set_processing_delay(180.0)

    # Allow telemetry to sample backends and update scores
    for _ in range(4):
        tb_adapt.telemetry.poll_backend("h2", "127.0.0.1", 9002)
        tb_adapt.telemetry.poll_backend("h3", "127.0.0.1", 9003)
        tb_adapt.telemetry.poll_backend("h4", "127.0.0.1", 9004)
        time.sleep(0.4)

    logger.info("\nInitial Adaptive Engine Scores prior to benchmark:")
    for sid, s in tb_adapt.engine.get_status_summary().items():
        logger.info(f"  {sid}: Latency={s['smoothed_latency_ms']}ms, Score={s['composite_score']}")

    logger.info("Executing 100 concurrent requests with Adaptive SDN scheduling...")
    gen_adapt = LoadGenerator(vip="127.0.0.1", port=8000, concurrency=12)
    adapt_result = gen_adapt.run_benchmark(num_requests=100)
    adapt_result.print_report("ADAPTIVE SDN LOAD BALANCING RESULTS")
    tb_adapt.stop()

    # ---------------------------------------------------------
    # PART 3: COMPARISON SUMMARY
    # ---------------------------------------------------------
    sep = "=" * 76
    print(f"\n{sep}")
    print(f" {'COMPREHENSIVE PERFORMANCE COMPARISON SUMMARY'.center(74)} ")
    print(sep)
    header = f" {'Metric':<30} | {'Round-Robin (Baseline)':<18} | {'Adaptive SDN':<18} "
    print(header)
    print("-" * 76)

    def print_row(label: str, rr_val: str, ad_val: str, improvement: str = ""):
        imp_str = f" ({improvement})" if improvement else ""
        print(f" {label:<30} | {rr_val:<18} | {ad_val:<18}{imp_str}")

    print_row("Total Requests", str(rr_result.total_requests), str(adapt_result.total_requests))
    print_row("Successful Requests", str(rr_result.successful_requests), str(adapt_result.successful_requests))
    print_row("Failed Requests", str(rr_result.failed_requests), str(adapt_result.failed_requests))
    print_row("Test Duration (s)", f"{rr_result.duration_sec:.2f} s", f"{adapt_result.duration_sec:.2f} s")
    
    tput_imp = f"+{((adapt_result.throughput_rps - rr_result.throughput_rps)/max(0.1, rr_result.throughput_rps))*100:.1f}%"
    print_row("Throughput (req/s)", f"{rr_result.throughput_rps:.2f}", f"{adapt_result.throughput_rps:.2f}", tput_imp)
    
    lat_imp = f"-{((rr_result.avg_latency_ms - adapt_result.avg_latency_ms)/max(0.1, rr_result.avg_latency_ms))*100:.1f}%"
    print_row("Mean Latency (ms)", f"{rr_result.avg_latency_ms:.2f} ms", f"{adapt_result.avg_latency_ms:.2f} ms", lat_imp)
    
    p95_imp = f"-{((rr_result.p95_latency_ms - adapt_result.p95_latency_ms)/max(0.1, rr_result.p95_latency_ms))*100:.1f}%"
    print_row("95th Percentile (p95)", f"{rr_result.p95_latency_ms:.2f} ms", f"{adapt_result.p95_latency_ms:.2f} ms", p95_imp)
    
    print("-" * 76)
    print(" Per-Server Connection Distribution:")
    for s_id in ["h2 (15ms)", "h3 (40ms)", "h4 (180ms)"]:
        raw_key = s_id.split()[0]
        rr_cnt = rr_result.server_counts.get(raw_key, 0)
        ad_cnt = adapt_result.server_counts.get(raw_key, 0)
        print(f"   {s_id:<28} | {rr_cnt:5d} requests ({rr_cnt/max(1, rr_result.successful_requests)*100:4.1f}%) | {ad_cnt:5d} requests ({ad_cnt/max(1, adapt_result.successful_requests)*100:4.1f}%)")
    print(f"{sep}\n")

    return rr_result, adapt_result


if __name__ == "__main__":
    run_scenario5()
