"""SSL certificate inspection utilities."""

from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime


def get_ssl_days_remaining(host: str, port: int = 443, timeout: float = 5.0) -> int:
    """Connects via TLS and returns the number of days until the certificate expires.

    Raises:
        socket.error: On network or connection failures.
        ssl.SSLError: On SSL handshake or verification failures.
        ValueError: If certificate has no expiration date.
    """
    ctx = ssl.create_default_context()
    with (
        socket.create_connection((host, port), timeout=timeout) as sock,
        ctx.wrap_socket(sock, server_hostname=host) as ssock,
    ):
        cert = ssock.getpeercert()
        if not cert or "notAfter" not in cert:
            raise ValueError(f"No SSL certificate or notAfter field returned for {host}:{port}")

        not_after_str = str(cert["notAfter"])
        expire_date = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
        now = datetime.now(UTC)
        return (expire_date - now).days
