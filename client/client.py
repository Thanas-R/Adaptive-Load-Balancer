"""TCP Client for SDN Load Balancer.

Sends single or sequential requests to the Virtual Service IP (VIP),
extracting the responder server ID and calculating accurate round-trip time.
"""

from __future__ import annotations

import json
import logging
import socket
import time
from typing import Optional, Tuple

logger = logging.getLogger("tcp_client")


class TcpClient:
    def __init__(self, vip: str = "10.0.0.100", port: int = 8000, timeout: float = 5.0):
        # Virtual IP target configuration
        self.vip = vip
        self.port = port
        self.timeout = timeout

    def send_request(self, payload: Optional[dict] = None) -> Tuple[bool, Optional[str], float, str]:
        # Send a single TCP request to the VIP and measure latency
        start_time = time.perf_counter()
        sock = None
        try:
            # Create low-level TCP socket and connect to VIP
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.vip, self.port))

            # Build HTTP-style request payload
            body_data = json.dumps(payload or {"action": "query", "timestamp": time.time()})
            request_str = (
                f"GET /service HTTP/1.1\r\n"
                f"Host: {self.vip}:{self.port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body_data)}\r\n"
                f"Connection: close\r\n\r\n"
                f"{body_data}"
            )
            sock.sendall(request_str.encode("utf-8"))

            # Receive full response in chunks
            response_chunks = []
            while True:
                chunk = sock.recv(2048)
                if not chunk:
                    break
                response_chunks.append(chunk)

            # Calculate total round-trip time in milliseconds
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            full_resp = b"".join(response_chunks).decode("utf-8", errors="replace")

            if not full_resp:
                return False, None, elapsed_ms, "Empty response"

            # Parse HTTP status header and JSON body
            parts = full_resp.split("\r\n\r\n", 1)
            header_part = parts[0]
            body_part = parts[1] if len(parts) > 1 else ""

            status_line = header_part.splitlines()[0] if header_part else ""
            is_ok = "200 OK" in status_line

            # Extract responder backend ID
            server_id = None
            if body_part:
                try:
                    data = json.loads(body_part)
                    server_id = data.get("server_id")
                except Exception:
                    pass

            return is_ok, server_id, elapsed_ms, "OK" if is_ok else status_line

        except (socket.timeout, socket.error, ConnectionRefusedError, OSError) as e:
            # Catch connection failure or timeout
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return False, None, elapsed_ms, str(e)
        finally:
            # Close client socket
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
