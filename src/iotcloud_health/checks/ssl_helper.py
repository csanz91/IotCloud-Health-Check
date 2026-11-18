"""SSL certificate inspection utilities."""

from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime

from iotcloud_health.checker import HealthCheckError, describe_error

# OpenSSL X509_V_ERR_CERT_HAS_EXPIRED
_X509_CERT_HAS_EXPIRED = 10


def get_ssl_days_remaining(host: str, port: int = 443, timeout: float = 5.0) -> int:
    """Connects via TLS and returns the number of days until the certificate expires.

    Raises:
        socket.error: On network or connection failures.
        ssl.SSLError: On SSL handshake or verification failures (including expiry).
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


def verify_certificate(
    host: str,
    port: int,
    *,
    label: str,
    impact: str,
    min_days_valid: int,
    timeout: float = 5.0,
) -> int:
    """Validates the TLS certificate of host:port and returns the days until expiry.

    Raises HealthCheckError with a tailored message when the handshake fails, the
    certificate has expired, or it expires within `min_days_valid` days.
    """
    try:
        days = get_ssl_days_remaining(host, port, timeout=timeout)
    except ssl.SSLCertVerificationError as err:
        # A default context verifies the chain, so an expired cert fails the handshake
        # itself; surface it as an expiry rather than a generic handshake failure.
        if err.verify_code == _X509_CERT_HAS_EXPIRED:
            raise HealthCheckError(
                f"🔴 [{label} SSL Expired] SSL certificate for {host} has expired! {impact}"
            ) from err
        raise HealthCheckError(
            f"🔴 [{label} SSL Failed] Certificate verification failed for {host}:{port}: "
            f"{err.verify_message or err}. {impact}"
        ) from err
    except (OSError, ssl.SSLError, ValueError) as err:
        raise HealthCheckError(
            f"🔴 [{label} SSL Failed] Failed SSL handshake for {host}:{port}: "
            f"{describe_error(err)}. {impact}"
        ) from err

    if days < 0:
        raise HealthCheckError(
            f"🔴 [{label} SSL Expired] SSL certificate for {host} has expired! {impact}"
        )
    if days <= min_days_valid:
        raise HealthCheckError(
            f"🔴 [{label} SSL Expiring Soon] SSL certificate for {host} expires in "
            f"{days} days! Immediate certificate renewal required."
        )
    return days
