"""API and Auth0 OIDC infrastructure health check."""

from __future__ import annotations

import logging
from typing import Any

import requests

from iotcloud_health.checker import HealthCheckError, check_service
from iotcloud_health.config import settings

logger = logging.getLogger("iotcloud_health.checks.api")


@check_service("api")
def check_api(session: requests.Session | None = None) -> dict[str, Any]:
    """Probes Auth0 OIDC endpoints and verifies internal API connectivity."""
    sess = session or requests.Session()

    # 1. Auth0 OIDC Discovery Contract
    auth0_domain = settings.auth0_domain.rstrip("/")
    oidc_url = f"{auth0_domain}/.well-known/openid-configuration"
    try:
        oidc_resp = sess.get(oidc_url, timeout=10)
    except requests.RequestException as err:
        raise HealthCheckError(
            "🔴 [Auth0 Down] Auth0 OIDC discovery endpoint is unreachable or returning "
            f"HTTP 0: {err}. Mobile app users will be unable to log in."
        ) from err

    if oidc_resp.status_code != 200:
        detail = oidc_resp.text
        raise HealthCheckError(
            "🔴 [Auth0 Down] Auth0 OIDC discovery endpoint is unreachable or returning "
            f"HTTP {oidc_resp.status_code}: {detail}. Mobile app users will be unable to log in.",
            status_code=oidc_resp.status_code,
            detail=detail,
        )

    oidc_data = oidc_resp.json()
    issuer = oidc_data.get("issuer", "")
    if auth0_domain not in issuer:
        raise HealthCheckError(
            f"🔴 [Auth0 Down] Auth0 OIDC discovery endpoint returned unexpected issuer '{issuer}'. "
            "Mobile app users will be unable to log in."
        )

    # 2. Auth0 JWKS Endpoint Contract
    jwks_url = f"{auth0_domain}/.well-known/jwks.json"
    try:
        jwks_resp = sess.get(jwks_url, timeout=10)
    except requests.RequestException as err:
        raise HealthCheckError(
            "🔴 [Auth0 Down] Auth0 OIDC discovery endpoint is unreachable or returning "
            f"HTTP 0: {err}. Mobile app users will be unable to log in."
        ) from err

    if jwks_resp.status_code != 200:
        detail = jwks_resp.text
        raise HealthCheckError(
            "🔴 [Auth0 Down] Auth0 OIDC discovery endpoint is unreachable or returning "
            f"HTTP {jwks_resp.status_code}: {detail}. Mobile app users will be unable to log in.",
            status_code=jwks_resp.status_code,
            detail=detail,
        )

    jwks_data = jwks_resp.json()
    keys = jwks_data.get("keys")
    if not isinstance(keys, list):
        raise HealthCheckError(
            "🔴 [Auth0 Down] Auth0 JWKS endpoint did not return valid key set. "
            "Mobile app users will be unable to log in."
        )

    # 3. Internal API Connectivity Probe
    internal_url = f"{settings.internal_api_url.rstrip('/')}/thermostats"
    m2m_headers = {"X-M2M-Token": settings.m2m_token}
    try:
        internal_resp = sess.get(internal_url, headers=m2m_headers, timeout=10)
    except requests.RequestException as err:
        raise HealthCheckError(
            f"🔴 [Internal API Down] Failed to connect to Internal API at "
            f"{settings.internal_api_url}: {err}."
        ) from err

    if internal_resp.status_code in (401, 403):
        raise HealthCheckError(
            "🔴 [M2M Auth Failed] Internal API rejected X-M2M-Token on /thermostats. "
            "Check M2M_TOKEN secret.",
            status_code=internal_resp.status_code,
        )

    if internal_resp.status_code != 200:
        detail = internal_resp.text
        raise HealthCheckError(
            f"🔴 [Internal API Error] Internal API returned HTTP {internal_resp.status_code}: "
            f"{detail}.",
            status_code=internal_resp.status_code,
            detail=detail,
        )

    logger.info("API health check passed (Auth0 OIDC + Internal API connected)")
    return {
        "auth0_issuer": issuer,
        "jwks_keys_count": len(keys),
        "internal_api_status": internal_resp.status_code,
    }
