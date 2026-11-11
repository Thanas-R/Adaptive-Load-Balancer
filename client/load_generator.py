"""Concurrent Load Generator and Performance Benchmark Tool.

Generates concurrent TCP requests to the Virtual Service IP, collecting:
- Request counts (total, succeeded, failed)
- Throughput (requests per second)
- Latency percentiles (min, avg, p50, p90, p95, p99, max)
- Per-server traffic distribution
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import math
import statistics
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from client.client import TcpClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("load_generator")


@dataclass
class BenchmarkResult:
    # Summary statistical counters
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    duration_sec: float = 0.0
    throughput_rps: float = 0.0
    latencies_ms: List[float] = field(default_factory=list)
    server_counts: Dict[str, int] = field(default_factory=dict)

    # Computed latency percentiles
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p90_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0

    def compute_summary(self) -> None:
        # Calculate throughput and latency percentiles
        if self.duration_sec > 0:
            self.throughput_rps = self.total_requests / self.duration_sec
        if self.latencies_ms:
            sorted_lat = sorted(self.latencies_ms)
            self.avg_latency_ms = statistics.mean(sorted_lat)
            self.min_latency_ms = sorted_lat[0]
            self.max_latency_ms = sorted_lat[-1]
            n = len(sorted_lat)
            self.p50_latency_ms = sorted_lat[int(0.50 * (n - 1))]
            self.p90_latency_ms = sorted_lat[int(0.90 * (n - 1))]
            self.p95_latency_ms = sorted_lat[int(0.95 * (n - 1))]
            self.p99_latency_ms = sorted_lat[int(0.99 * (n - 1))]

    def print_report(self, title: str = "BENCHMARK REPORT") -> None:
        # Format and display terminal benchmark report
        self.compute_summary()
        sep = "=" * 64
        print(f"\n{sep}")
        print(f" {title.center(62)} ")
        print(sep)
        print(f" Total Requests:      {self.total_requests}")
        print(f" Successful Requests: {self.successful_requests} ({self.successful_requests/max(1, self.total_requests)*100:.1f}%)")
        print(f" Failed Requests:     {self.failed_requests}")
        print(f" Test Duration:       {self.duration_sec:.2f} s")
        print(f" Throughput:          {self.throughput_rps:.2f} req/sec")
        print("-" * 64)
        print(" Latency Statistics (ms):")
        print(f"   Min:    {self.min_latency_ms:.2f} ms")
        print(f"   Avg:    {self.avg_latency_ms:.2f} ms")
        print(f"   Median: {self.p50_latency_ms:.2f} ms")
        print(f"   p90:    {self.p90_latency_ms:.2f} ms")
        print(f"   p95:    {self.p95_latency_ms:.2f} ms")
        print(f"   p99:    {self.p99_latency_ms:.2f} ms")
        print(f"   Max:    {self.max_latency_ms:.2f} ms")
        print("-" * 64)
        print(" Traffic Distribution Across Backends:")
        for s_id, count in sorted(self.server_counts.items()):
            pct = (count / max(1, self.successful_requests)) * 100.0
            bar = "#" * int(pct / 4)
            print(f"   {s_id:6s}: {count:5d} requests ({pct:5.1f}%) [{bar}]")
        print(f"{sep}\n")


class LoadGenerator:
    def __init__(
        self,
        vip: str = "10.0.0.100",
        port: int = 8000,
        concurrency: int = 10,
        timeout: float = 4.0,
    ):
        # Target endpoint and thread concurrency level
        self.vip = vip
        self.port = port
        self.concurrency = concurrency
        self.timeout = timeout

    def run_benchmark(
        self,
        num_requests: int = 100,
        rate_limit_rps: Optional[float] = None,
    ) -> BenchmarkResult:
        # Execute concurrent load using a thread pool
        result = BenchmarkResult(total_requests=num_requests)
        client = TcpClient(self.vip, self.port, timeout=self.timeout)
        start_time = time.perf_counter()
        delay_between_requests = 1.0 / rate_limit_rps if rate_limit_rps else 0.0

        # Worker function executed by thread pool
        def worker(req_idx: int) -> Tuple[bool, Optional[str], float]:
            if delay_between_requests > 0:
                time.sleep(delay_between_requests * (req_idx % self.concurrency))
            ok, s_id, lat, _ = client.send_request({"request_id": req_idx})
            return ok, s_id, lat

        # Submit tasks concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = [executor.submit(worker, i) for i in range(num_requests)]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    ok, s_id, lat = fut.result()
                    if ok and s_id:
                        result.successful_requests += 1
                        result.latencies_ms.append(lat)
                        result.server_counts[s_id] = result.server_counts.get(s_id, 0) + 1
                    else:
                        result.failed_requests += 1
                except Exception:
                    result.failed_requests += 1

        # Finalize duration and compute statistics
        result.duration_sec = time.perf_counter() - start_time
        result.compute_summary()
        return result


def main():
    # CLI interface for load generator
    parser = argparse.ArgumentParser(description="SDN Load Generator")
    parser.add_argument("--vip", default="10.0.0.100", help="Virtual IP")
    parser.add_argument("--port", type=int, default=8000, help="Service Port")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrency")
    parser.add_argument("--requests", type=int, default=100, help="Total requests")
    parser.add_argument("--rate", type=float, default=None, help="Rate limit RPS")
    args = parser.parse_args()

    gen = LoadGenerator(args.vip, args.port, concurrency=args.concurrency)
    res = gen.run_benchmark(num_requests=args.requests, rate_limit_rps=args.rate)
    res.print_report()


if __name__ == "__main__":
    main()
