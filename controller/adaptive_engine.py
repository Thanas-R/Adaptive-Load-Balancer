"""Adaptive Load Balancing Engine.

Calculates composite load scores from telemetry metrics:
- Active connections (50% default weight)
- Smoothed response latency (35% default weight, EMA)
- Error rate (15% default weight)

Performs metric normalization, server health monitoring, failover,
and gradual recovery warming.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("adaptive_engine")


@dataclass
class BackendStats:
    # Static server identity and connection parameters
    server_id: str
    ip: str
    mac: str
    service_port: int
    telemetry_port: int
    switch_port: int
    capacity: int = 100

    # Dynamic metrics collected from telemetry agent
    active_connections: int = 0
    total_requests: int = 0
    failed_requests: int = 0
    error_rate: float = 0.0
    last_raw_latency_ms: float = 20.0
    smoothed_latency_ms: float = 20.0
    cpu_utilization: float = 0.0
    link_utilization: float = 0.0
    rx_bytes: int = 0
    tx_bytes: int = 0

    # Server health state tracking
    health_status: str = "HEALTHY"
    consecutive_failures: int = 0
    last_heartbeat: float = field(default_factory=time.time)
    recovery_start_time: Optional[float] = None

    # Routing and composite scoring outputs
    last_score: float = 0.0
    total_flows_routed: int = 0


class AdaptiveEngine:
    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        ema_alpha: float = 0.25,
        max_consecutive_failures: int = 3,
        recovery_cooldown_sec: float = 5.0,
        mode: str = "adaptive",
    ):
        # Configure metric weights and normalize to sum to 1.0
        self.weights = weights or {
            "active_connections": 0.50,
            "smoothed_latency": 0.35,
            "error_rate": 0.15,
        }
        total_w = sum(self.weights.values())
        if total_w > 0:
            self.weights = {k: v / total_w for k, v in self.weights.items()}

        # Tuning parameters for smoothing and failure detection
        self.ema_alpha = ema_alpha
        self.max_consecutive_failures = max_consecutive_failures
        self.recovery_cooldown_sec = recovery_cooldown_sec
        self.mode = mode.lower()

        # Backend storage and round-robin index pointer
        self.backends: Dict[str, BackendStats] = {}
        self._rr_index: int = 0
        self._lock = threading.RLock()

    def register_backend(
        self,
        server_id: str,
        ip: str,
        mac: str,
        service_port: int,
        telemetry_port: int,
        switch_port: int,
        capacity: int = 100,
        initial_delay_ms: float = 20.0,
    ) -> None:
        # Register backend node into adaptive engine pool
        with self._lock:
            stats = BackendStats(
                server_id=server_id,
                ip=ip,
                mac=mac,
                service_port=service_port,
                telemetry_port=telemetry_port,
                switch_port=switch_port,
                capacity=capacity,
                last_raw_latency_ms=initial_delay_ms,
                smoothed_latency_ms=initial_delay_ms,
                last_heartbeat=time.time(),
            )
            self.backends[server_id] = stats
            logger.info(f"Registered backend {server_id} ({ip}:{service_port}) on switch port {switch_port}")

    def update_telemetry(self, server_id: str, data: dict) -> None:
        # Update server metrics reported by telemetry collector
        with self._lock:
            backend = self.backends.get(server_id)
            if not backend:
                logger.warning(f"Telemetry received for unknown server: {server_id}")
                return

            now = time.time()
            backend.last_heartbeat = now
            backend.consecutive_failures = 0

            # State transition for recovering servers
            if backend.health_status == "UNHEALTHY":
                backend.health_status = "RECOVERING"
                backend.recovery_start_time = now
                logger.info(f"Backend {server_id} transitioned from UNHEALTHY to RECOVERING.")
            elif backend.health_status == "RECOVERING":
                if backend.recovery_start_time and (now - backend.recovery_start_time) >= self.recovery_cooldown_sec:
                    backend.health_status = "HEALTHY"
                    backend.recovery_start_time = None
                    logger.info(f"Backend {server_id} completed recovery cooldown; status is now HEALTHY.")

            # Update connection counts and request metrics
            if "active_connections" in data:
                backend.active_connections = max(0, int(data["active_connections"]))

            if "total_requests" in data:
                backend.total_requests = int(data["total_requests"])

            if "failed_requests" in data:
                backend.failed_requests = int(data["failed_requests"])

            if "error_rate" in data:
                backend.error_rate = max(0.0, min(1.0, float(data["error_rate"])))
            elif backend.total_requests > 0:
                backend.error_rate = backend.failed_requests / float(backend.total_requests)

            # Apply Exponential Moving Average for latency smoothing
            if "raw_latency_ms" in data:
                raw_lat = max(0.1, float(data["raw_latency_ms"]))
                backend.last_raw_latency_ms = raw_lat
                backend.smoothed_latency_ms = (
                    self.ema_alpha * raw_lat + (1.0 - self.ema_alpha) * backend.smoothed_latency_ms
                )
            elif "smoothed_latency_ms" in data:
                backend.smoothed_latency_ms = max(0.1, float(data["smoothed_latency_ms"]))

            if "cpu_utilization" in data:
                backend.cpu_utilization = float(data["cpu_utilization"])

            if "link_utilization" in data:
                backend.link_utilization = max(0.0, min(1.0, float(data["link_utilization"])))

            if "rx_bytes" in data:
                backend.rx_bytes = int(data["rx_bytes"])

            if "tx_bytes" in data:
                backend.tx_bytes = int(data["tx_bytes"])

            # Degradation threshold checking
            if backend.health_status == "HEALTHY":
                if backend.error_rate >= 0.25 or backend.smoothed_latency_ms >= 500.0 or backend.link_utilization >= 0.90:
                    backend.health_status = "DEGRADED"
                    logger.warning(f"Backend {server_id} marked DEGRADED: Latency={backend.smoothed_latency_ms:.1f}ms")
            elif backend.health_status == "DEGRADED":
                if backend.error_rate < 0.10 and backend.smoothed_latency_ms < 200.0 and backend.link_utilization < 0.70:
                    backend.health_status = "HEALTHY"
                    logger.info(f"Backend {server_id} restored to HEALTHY.")

    def record_probe_failure(self, server_id: str) -> None:
        # Mark consecutive heartbeat failures and flag unhealthy status
        with self._lock:
            backend = self.backends.get(server_id)
            if not backend:
                return
            backend.consecutive_failures += 1
            if backend.consecutive_failures >= self.max_consecutive_failures:
                if backend.health_status != "UNHEALTHY":
                    backend.health_status = "UNHEALTHY"
                    backend.recovery_start_time = None
                    logger.error(
                        f"Backend {server_id} ({backend.ip}) marked UNHEALTHY after "
                        f"{backend.consecutive_failures} consecutive probe failures."
                    )

    def get_eligible_backends(self) -> List[BackendStats]:
        # Filter available servers currently eligible for routing
        with self._lock:
            eligible = []
            for b in self.backends.values():
                if b.health_status != "UNHEALTHY":
                    eligible.append(b)
            return eligible

    def calculate_scores(self) -> Dict[str, Tuple[float, Dict[str, float]]]:
        # Compute min-max normalized composite score for each eligible backend
        with self._lock:
            eligible = self.get_eligible_backends()
            if not eligible:
                return {}

            # Collect raw values for normalization across active pool
            conns = [float(b.active_connections) for b in eligible]
            latencies = [b.smoothed_latency_ms for b in eligible]
            errors = [b.error_rate for b in eligible]
            utils = [b.link_utilization for b in eligible]

            min_c, max_c = min(conns), max(conns)
            min_l, max_l = min(latencies), max(latencies)
            min_e, max_e = min(errors), max(errors)
            min_u, max_u = min(utils), max(utils)

            results = {}
            w_conn = self.weights.get("active_connections", 0.0)
            w_lat = self.weights.get("smoothed_latency", 0.0)
            w_err = self.weights.get("error_rate", 0.0)
            w_util = self.weights.get("link_utilization", 0.0)

            for b in eligible:
                # Min-max normalization into range 0.0 to 1.0
                norm_c = (b.active_connections - min_c) / (max_c - min_c) if max_c > min_c else 0.0
                norm_l = (b.smoothed_latency_ms - min_l) / (max_l - min_l) if max_l > min_l else 0.0
                norm_e = (b.error_rate - min_e) / (max_e - min_e) if max_e > min_e else 0.0
                norm_u = (b.link_utilization - min_u) / (max_u - min_u) if max_u > min_u else 0.0

                composite = (w_conn * norm_c) + (w_lat * norm_l) + (w_err * norm_e) + (w_util * norm_u)

                # Penalize recovering or degraded nodes to prevent traffic overload
                if b.health_status == "RECOVERING":
                    composite += 0.35
                elif b.health_status == "DEGRADED":
                    composite += 0.20

                b.last_score = composite
                results[b.server_id] = (
                    composite,
                    {
                        "norm_conn": norm_c,
                        "norm_lat": norm_l,
                        "norm_err": norm_e,
                        "norm_util": norm_u,
                        "raw_conn": b.active_connections,
                        "raw_lat": b.smoothed_latency_ms,
                        "raw_err": b.error_rate,
                        "raw_util": b.link_utilization,
                        "status": b.health_status,
                    },
                )
            return results

    def select_backend(self, algorithm_override: Optional[str] = None) -> Optional[BackendStats]:
        # Choose backend server according to active load balancing algorithm
        with self._lock:
            algo = (algorithm_override or self.mode).lower()
            eligible = self.get_eligible_backends()
            if not eligible:
                logger.error("No eligible backends available for routing!")
                return None

            # Static Round-Robin baseline
            if algo == "round_robin":
                candidates = [b for b in eligible if b.health_status in ("HEALTHY", "DEGRADED", "RECOVERING")]
                if not candidates:
                    candidates = eligible
                self._rr_index = (self._rr_index + 1) % len(candidates)
                selected = candidates[self._rr_index]
                selected.total_flows_routed += 1
                return selected

            # Random selection baseline
            if algo == "random":
                import random
                candidates = [b for b in eligible if b.health_status in ("HEALTHY", "DEGRADED", "RECOVERING")]
                if not candidates:
                    candidates = eligible
                selected = random.choice(candidates)
                selected.total_flows_routed += 1
                return selected

            # Adaptive algorithm: pick node with minimum composite score
            scores = self.calculate_scores()
            if not scores:
                return None

            sorted_candidates = sorted(
                eligible,
                key=lambda b: (scores[b.server_id][0], b.active_connections, b.smoothed_latency_ms),
            )
            selected = sorted_candidates[0]
            selected.total_flows_routed += 1
            return selected

    def calculate_load_variance(self) -> float:
        # Calculate variance of active connections across eligible servers
        with self._lock:
            eligible = self.get_eligible_backends()
            if len(eligible) <= 1:
                return 0.0
            loads = [float(b.active_connections) for b in eligible]
            mean = sum(loads) / len(loads)
            variance = sum((x - mean) ** 2 for x in loads) / len(loads)
            return variance

    def get_status_summary(self) -> Dict[str, dict]:
        # Provide dictionary summary for telemetry logging and dashboards
        with self._lock:
            scores = self.calculate_scores()
            summary = {}
            for sid, b in self.backends.items():
                score_val = scores.get(sid, (999.0, {}))[0] if b.health_status != "UNHEALTHY" else 999.0
                summary[sid] = {
                    "ip": b.ip,
                    "switch_port": b.switch_port,
                    "status": b.health_status,
                    "active_connections": b.active_connections,
                    "raw_latency_ms": round(b.last_raw_latency_ms, 2),
                    "smoothed_latency_ms": round(b.smoothed_latency_ms, 2),
                    "error_rate": round(b.error_rate, 4),
                    "composite_score": round(score_val, 4),
                    "total_flows_routed": b.total_flows_routed,
                }
            return summary
