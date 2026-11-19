from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("adaptive_engine")


@dataclass
class BackendStats:
    server_id: str
    ip: str
    mac: str
    service_port: int
    telemetry_port: int
    switch_port: int
    capacity: int = 100
    telemetry_ip: Optional[str] = None

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

    health_status: str = "HEALTHY"
    consecutive_failures: int = 0
    has_heartbeat: bool = False
    last_heartbeat: float = field(default_factory=time.time)
    recovery_start_time: Optional[float] = None

    last_score: float = 0.0
    total_flows_routed: int = 0
    in_flight: int = 0


class AdaptiveEngine:
    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        ema_alpha: float = 0.25,
        max_consecutive_failures: int = 3,
        recovery_cooldown_sec: float = 5.0,
        degraded_latency_ms: float = 150.0,
        latency_tolerance_ms: float = 5.0,
        mode: str = "adaptive",
    ):
        self.weights = weights or {
            "active_connections": 0.50,
            "smoothed_latency": 0.35,
            "error_rate": 0.15,
        }
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {key: value / total for key, value in self.weights.items()}

        self.ema_alpha = ema_alpha
        self.max_consecutive_failures = max_consecutive_failures
        self.recovery_cooldown_sec = recovery_cooldown_sec
        self.degraded_latency_ms = degraded_latency_ms
        self.latency_tolerance_ms = max(1e-6, latency_tolerance_ms)
        self.mode = mode.lower()

        self.backends: Dict[str, BackendStats] = {}
        self._rr_index = 0
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
        telemetry_ip: Optional[str] = None,
    ) -> None:
        with self._lock:
            self.backends[server_id] = BackendStats(
                server_id=server_id,
                ip=ip,
                mac=mac,
                service_port=service_port,
                telemetry_port=telemetry_port,
                switch_port=switch_port,
                capacity=capacity,
                telemetry_ip=telemetry_ip,
                last_raw_latency_ms=initial_delay_ms,
                smoothed_latency_ms=initial_delay_ms,
                last_heartbeat=time.time(),
            )
            logger.info(
                "Registered %s on %s:%s, switch port %s",
                server_id,
                ip,
                service_port,
                switch_port,
            )

    def update_telemetry(self, server_id: str, data: dict) -> None:
        with self._lock:
            backend = self.backends.get(server_id)
            if not backend:
                logger.warning("Telemetry for unknown backend: %s", server_id)
                return

            now = time.time()
            backend.has_heartbeat = True
            backend.last_heartbeat = now
            backend.consecutive_failures = 0

            # State transitions
            if backend.health_status == "UNHEALTHY":
                backend.health_status = "RECOVERING"
                backend.recovery_start_time = now
                logger.info("%s is RECOVERING", server_id)
            elif backend.health_status == "RECOVERING":
                started = backend.recovery_start_time
                if started is not None and now - started >= self.recovery_cooldown_sec:
                    backend.health_status = "HEALTHY"
                    backend.recovery_start_time = None
                    logger.info("%s is HEALTHY", server_id)

            if "active_connections" in data:
                backend.active_connections = max(0, int(data["active_connections"]))
                backend.in_flight = min(backend.in_flight, backend.active_connections)
            if "total_requests" in data:
                backend.total_requests = max(0, int(data["total_requests"]))
            if "failed_requests" in data:
                backend.failed_requests = max(0, int(data["failed_requests"]))

            if "error_rate" in data:
                backend.error_rate = max(0.0, min(1.0, float(data["error_rate"])))
            elif backend.total_requests > 0:
                backend.error_rate = backend.failed_requests / float(backend.total_requests)

            if "raw_latency_ms" in data:
                raw = max(0.1, float(data["raw_latency_ms"]))
                backend.last_raw_latency_ms = raw
                backend.smoothed_latency_ms = (
                    self.ema_alpha * raw + (1.0 - self.ema_alpha) * backend.smoothed_latency_ms
                )
            elif "smoothed_latency_ms" in data:
                backend.smoothed_latency_ms = max(0.1, float(data["smoothed_latency_ms"]))

            if "cpu_utilization" in data:
                backend.cpu_utilization = max(0.0, min(1.0, float(data["cpu_utilization"])))
            if "link_utilization" in data:
                backend.link_utilization = max(0.0, min(1.0, float(data["link_utilization"])))
            if "rx_bytes" in data:
                backend.rx_bytes = max(0, int(data["rx_bytes"]))
            if "tx_bytes" in data:
                backend.tx_bytes = max(0, int(data["tx_bytes"]))

            if backend.health_status == "HEALTHY":
                if (
                    backend.error_rate >= 0.25
                    or backend.smoothed_latency_ms >= self.degraded_latency_ms
                    or backend.link_utilization >= 0.90
                ):
                    backend.health_status = "DEGRADED"
                    logger.warning(
                        "%s is DEGRADED, latency %.1f ms, error rate %.2f",
                        server_id,
                        backend.smoothed_latency_ms,
                        backend.error_rate,
                    )
            elif backend.health_status == "DEGRADED":
                if (
                    backend.error_rate < 0.10
                    and backend.smoothed_latency_ms < self.degraded_latency_ms * 0.8
                    and backend.link_utilization < 0.70
                ):
                    backend.health_status = "HEALTHY"
                    logger.info("%s is HEALTHY", server_id)

    def record_probe_failure(self, server_id: str) -> None:
        with self._lock:
            backend = self.backends.get(server_id)
            if not backend or not backend.has_heartbeat:
                return

            backend.consecutive_failures += 1
            if backend.consecutive_failures < self.max_consecutive_failures:
                return

            if backend.health_status != "UNHEALTHY":
                backend.health_status = "UNHEALTHY"
                backend.recovery_start_time = None
                logger.error(
                    "%s is UNHEALTHY after %s failed probes",
                    server_id,
                    backend.consecutive_failures,
                )

    def get_eligible_backends(self) -> List[BackendStats]:
        with self._lock:
            return [backend for backend in self.backends.values() if backend.health_status != "UNHEALTHY"]

    def _effective_connections(self, backend: BackendStats) -> int:
        return max(backend.active_connections, backend.in_flight)

    def release_backend(self, server_id: str) -> None:
        with self._lock:
            backend = self.backends.get(server_id)
            if backend and backend.in_flight > 0:
                backend.in_flight -= 1

    def calculate_scores(self) -> Dict[str, Tuple[float, Dict[str, float]]]:
        with self._lock:
            eligible = self.get_eligible_backends()
            if not eligible:
                return {}

            connections = [float(self._effective_connections(backend)) for backend in eligible]
            latencies = [backend.smoothed_latency_ms for backend in eligible]
            errors = [backend.error_rate for backend in eligible]
            utilization = [backend.link_utilization for backend in eligible]

            min_c, max_c = min(connections), max(connections)
            min_l, max_l = min(latencies), max(latencies)
            min_e, max_e = min(errors), max(errors)
            min_u, max_u = min(utilization), max(utilization)

            w_conn = self.weights.get("active_connections", 0.0)
            w_lat = self.weights.get("smoothed_latency", 0.0)
            w_err = self.weights.get("error_rate", 0.0)
            w_util = self.weights.get("link_utilization", 0.0)

            latency_span = max(max_l - min_l, self.latency_tolerance_ms)
            results: Dict[str, Tuple[float, Dict[str, float]]] = {}
            for backend in eligible:
                effective_connections = self._effective_connections(backend)
                norm_c = (effective_connections - min_c) / (max_c - min_c) if max_c > min_c else 0.0
                norm_l = (backend.smoothed_latency_ms - min_l) / latency_span
                norm_e = (backend.error_rate - min_e) / (max_e - min_e) if max_e > min_e else 0.0
                norm_u = (backend.link_utilization - min_u) / (max_u - min_u) if max_u > min_u else 0.0

                score = (
                    w_conn * norm_c
                    + w_lat * norm_l
                    + w_err * norm_e
                    + w_util * norm_u
                )

                if backend.health_status == "RECOVERING":
                    score += 0.35
                elif backend.health_status == "DEGRADED":
                    score += 0.20

                backend.last_score = score
                results[backend.server_id] = (
                    score,
                    {
                        "norm_conn": norm_c,
                        "norm_lat": norm_l,
                        "norm_err": norm_e,
                        "norm_util": norm_u,
                        "raw_conn": effective_connections,
                        "raw_lat": backend.smoothed_latency_ms,
                        "raw_err": backend.error_rate,
                        "raw_util": backend.link_utilization,
                        "status": backend.health_status,
                    },
                )
            return results

    def select_backend(
        self,
        algorithm_override: Optional[str] = None,
        exclude: Optional[Set[str]] = None,
    ) -> Optional[BackendStats]:
        with self._lock:
            algorithm = (algorithm_override or self.mode).lower()
            eligible = [
                backend
                for backend in self.get_eligible_backends()
                if not exclude or backend.server_id not in exclude
            ]
            if not eligible:
                logger.error("No eligible backends")
                return None

            if algorithm == "round_robin":
                candidates = [
                    backend
                    for backend in eligible
                    if backend.health_status in ("HEALTHY", "DEGRADED", "RECOVERING")
                ] or eligible
                selected = candidates[self._rr_index % len(candidates)]
                self._rr_index = (self._rr_index + 1) % len(candidates)
                selected.total_flows_routed += 1
                selected.in_flight += 1
                return selected

            if algorithm == "random":
                selected = random.choice(eligible)
                selected.total_flows_routed += 1
                selected.in_flight += 1
                return selected

            scores = self.calculate_scores()
            if not scores:
                return None

            def score_key(backend: BackendStats) -> Tuple[float, int, float]:
                return (
                    scores[backend.server_id][0],
                    self._effective_connections(backend),
                    backend.smoothed_latency_ms,
                )

            best_key = min(score_key(backend) for backend in eligible)
            candidates = [backend for backend in eligible if score_key(backend) == best_key]
            if len(candidates) > 1:
                selected = candidates[self._rr_index % len(candidates)]
                self._rr_index = (self._rr_index + 1) % len(candidates)
            else:
                selected = candidates[0]

            selected.total_flows_routed += 1
            selected.in_flight += 1
            return selected

    def calculate_load_variance(self) -> float:
        with self._lock:
            eligible = self.get_eligible_backends()
            if len(eligible) <= 1:
                return 0.0
            loads = [float(backend.active_connections) for backend in eligible]
            mean = sum(loads) / len(loads)
            return sum((load - mean) ** 2 for load in loads) / len(loads)

    def get_status_summary(self) -> Dict[str, dict]:
        with self._lock:
            scores = self.calculate_scores()
            summary = {}
            for server_id, backend in self.backends.items():
                score = scores.get(server_id, (999.0, {}))[0] if backend.health_status != "UNHEALTHY" else 999.0
                summary[server_id] = {
                    "ip": backend.ip,
                    "switch_port": backend.switch_port,
                    "status": backend.health_status,
                    "active_connections": self._effective_connections(backend),
                    "in_flight": backend.in_flight,
                    "raw_latency_ms": round(backend.last_raw_latency_ms, 2),
                    "smoothed_latency_ms": round(backend.smoothed_latency_ms, 2),
                    "error_rate": round(backend.error_rate, 4),
                    "composite_score": round(score, 4),
                    "total_flows_routed": backend.total_flows_routed,
                }
            return summary
