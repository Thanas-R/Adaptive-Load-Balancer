from __future__ import annotations

import argparse
import concurrent.futures
import logging
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
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    duration_sec: float = 0.0
    throughput_rps: float = 0.0
    latencies_ms: List[float] = field(default_factory=list)
    server_counts: Dict[str, int] = field(default_factory=dict)

    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p90_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0

    def compute_summary(self) -> None:
        if self.duration_sec > 0:
            self.throughput_rps = self.total_requests / self.duration_sec

        if not self.latencies_ms:
            return

        ordered = sorted(self.latencies_ms)
        count = len(ordered)
        self.avg_latency_ms = statistics.mean(ordered)
        self.min_latency_ms = ordered[0]
        self.max_latency_ms = ordered[-1]
        self.p50_latency_ms = ordered[int(0.50 * (count - 1))]
        self.p90_latency_ms = ordered[int(0.90 * (count - 1))]
        self.p95_latency_ms = ordered[int(0.95 * (count - 1))]
        self.p99_latency_ms = ordered[int(0.99 * (count - 1))]

    def print_report(self, title: str = "BENCHMARK REPORT") -> None:
        self.compute_summary()
        separator = "=" * 64
        print(f"\n{separator}")
        print(f" {title.center(62)} ")
        print(separator)
        print(f" Total Requests:      {self.total_requests}")
        print(
            f" Successful Requests: {self.successful_requests} "
            f"({self.successful_requests / max(1, self.total_requests) * 100:.1f}%)"
        )
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
        for server_id, count in sorted(self.server_counts.items()):
            share = (count / max(1, self.successful_requests)) * 100.0
            bar = "#" * int(share / 4)
            print(f"   {server_id:6s}: {count:5d} requests ({share:5.1f}%) [{bar}]")
        print(f"{separator}\n")


class LoadGenerator:
    def __init__(
        self,
        vip: str = "10.0.0.100",
        port: int = 8000,
        concurrency: int = 10,
        timeout: float = 4.0,
    ):
        self.vip = vip
        self.port = port
        self.concurrency = max(1, concurrency)
        self.timeout = timeout

    def run_benchmark(
        self,
        num_requests: int = 100,
        rate_limit_rps: Optional[float] = None,
    ) -> BenchmarkResult:
        result = BenchmarkResult(total_requests=num_requests)
        client = TcpClient(self.vip, self.port, timeout=self.timeout)
        start_time = time.perf_counter()
        interval = 1.0 / rate_limit_rps if rate_limit_rps and rate_limit_rps > 0 else 0.0

        def worker(request_id: int) -> Tuple[bool, Optional[str], float]:
            if interval > 0:
                target = start_time + request_id * interval
                delay = target - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)

            ok, server_id, latency, _ = client.send_request({"request_id": request_id})
            return ok, server_id, latency

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [pool.submit(worker, index) for index in range(num_requests)]
            for future in concurrent.futures.as_completed(futures):
                try:
                    ok, server_id, latency = future.result()
                    if ok and server_id:
                        result.successful_requests += 1
                        result.latencies_ms.append(latency)
                        result.server_counts[server_id] = result.server_counts.get(server_id, 0) + 1
                    else:
                        result.failed_requests += 1
                except Exception:
                    result.failed_requests += 1

        result.duration_sec = time.perf_counter() - start_time
        result.compute_summary()
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="SDN load generator")
    parser.add_argument("--vip", default="10.0.0.100", help="virtual service IP")
    parser.add_argument("--port", type=int, default=8000, help="service port")
    parser.add_argument("--concurrency", type=int, default=10, help="parallel workers")
    parser.add_argument("--requests", type=int, default=100, help="total requests")
    parser.add_argument("--rate", type=float, default=None, help="requests per second")
    args = parser.parse_args()

    generator = LoadGenerator(args.vip, args.port, concurrency=args.concurrency)
    result = generator.run_benchmark(num_requests=args.requests, rate_limit_rps=args.rate)
    result.print_report()


if __name__ == "__main__":
    main()
