"""Public API and external SSL certificate health check."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import requests

from iotcloud_health.checker import (
    HealthCheckError,
    check_service,
    describe_error,
    get_session,
    response_detail,
)
from iotcloud_health.checks.ssl_helper import verify_certificate
from iotcloud_health.config import settings

logger = logging.getLogger("iotcloud_health.checks.public_api")


@check_service("public_api")
def check_public_api(
    url: str | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Probes the public API endpoint externally and verifies SSL certificate validity."""
    target_url = url or settings.public_api_url
    sess = session or get_session()

    parsed = urlparse(target_url)
    host = parsed.hostname or ""
    is_https = parsed.scheme == "https"
    port = parsed.port or (443 if is_https else 80)

    ssl_days_remaining: int | None = None

    # 1. SSL Certificate Verification (if HTTPS)
    if is_https and host:
        ssl_days_remaining = verify_certificate(
            host,
            port,
            label="Public",
            impact="Mobile app users cannot establish a secure connection.",
            min_days_valid=settings.ssl_min_days_valid,
        )

    # 2. HTTP Endpoint Reachability Probe
    try:
        resp = sess.get(target_url, timeout=10)
    except requests.RequestException as err:
        raise HealthCheckError(
            f"🔴 [Public API Down] Failed to connect to Public API at {target_url}: "
            f"{describe_error(err)}. "
            "External mobile app access is blocked."
        ) from err

    if resp.status_code != 200:
        detail = response_detail(resp)
        raise HealthCheckError(
            f"🔴 [Public API Error] Public API at {target_url} returned HTTP "
            f"{resp.status_code}: {detail}. Mobile app users may experience outages.",
            status_code=resp.status_code,
            detail=detail,
        )

    # 3. Payload sanity verification (only if the body is a JSON object with a status)
    try:
        data = resp.json()
    except ValueError:
        data = None
    status_val = data.get("status") if isinstance(data, dict) else None
    if status_val and status_val != "healthy":
        raise HealthCheckError(
            f"🔴 [Public API Unhealthy] Public API returned status '{status_val}'. "
            "Expected 'healthy'."
        )

    logger.info(
        "Public API health check passed (%s, status 200, SSL %s days remaining)",
        target_url,
        ssl_days_remaining,
    )
    return {
        "url": target_url,
        "status_code": resp.status_code,
        "ssl_days_remaining": ssl_days_remaining,
    }
