from __future__ import annotations

import json
import socket
import time
from typing import Optional, Tuple


class TcpClient:
    def __init__(self, vip: str = "10.0.0.100", port: int = 8000, timeout: float = 5.0):
        self.vip = vip
        self.port = port
        self.timeout = timeout

    def send_request(self, payload: Optional[dict] = None) -> Tuple[bool, Optional[str], float, str]:
        start_time = time.perf_counter()
        sock: Optional[socket.socket] = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.vip, self.port))

            body = json.dumps(payload or {"action": "query", "timestamp": time.time()})
            request = (
                f"GET /service HTTP/1.1\r\n"
                f"Host: {self.vip}:{self.port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
                f"{body}"
            )
            sock.sendall(request.encode("utf-8"))

            chunks = []
            while True:
                chunk = sock.recv(2048)
                if not chunk:
                    break
                chunks.append(chunk)

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            response = b"".join(chunks).decode("utf-8", errors="replace")
            if not response:
                return False, None, elapsed_ms, "Empty response"

            header, _, body_part = response.partition("\r\n\r\n")
            status_line = header.splitlines()[0] if header else ""
            is_ok = "200 OK" in status_line

            server_id = None
            if body_part:
                try:
                    server_id = json.loads(body_part).get("server_id")
                except (ValueError, AttributeError):
                    server_id = None

            return is_ok, server_id, elapsed_ms, "OK" if is_ok else status_line

        except OSError as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return False, None, elapsed_ms, str(exc)
        finally:
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
