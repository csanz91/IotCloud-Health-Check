"""API and Auth0 OIDC infrastructure health check."""

from __future__ import annotations

import logging
from typing import Any

import requests

from iotcloud_health.checker import (
    HealthCheckError,
    check_service,
    describe_error,
    get_session,
    response_detail,
)
from iotcloud_health.config import settings

logger = logging.getLogger("iotcloud_health.checks.api")

_AUTH0_IMPACT = "Mobile app users will be unable to log in."


def _fetch_auth0_json(sess: requests.Session, url: str, endpoint_name: str) -> Any:
    """GETs an Auth0 well-known document, raising a tailored HealthCheckError on failure."""
    try:
        resp = sess.get(url, timeout=10)
    except requests.RequestException as err:
        raise HealthCheckError(
            f"🔴 [Auth0 Down] Auth0 {endpoint_name} endpoint is unreachable: "
            f"{describe_error(err)}. {_AUTH0_IMPACT}"
        ) from err

    if resp.status_code != 200:
        detail = response_detail(resp)
        raise HealthCheckError(
            f"🔴 [Auth0 Down] Auth0 {endpoint_name} endpoint returned HTTP "
            f"{resp.status_code}: {detail}. {_AUTH0_IMPACT}",
            status_code=resp.status_code,
            detail=detail,
        )

    try:
        return resp.json()
    except ValueError as err:
        raise HealthCheckError(
            f"🔴 [Auth0 Down] Auth0 {endpoint_name} endpoint returned invalid JSON: "
            f"{response_detail(resp)}. {_AUTH0_IMPACT}"
        ) from err


@check_service("api")
def check_api(session: requests.Session | None = None) -> dict[str, Any]:
    """Probes Auth0 OIDC endpoints and verifies internal API connectivity."""
    sess = session or get_session()

    # 1. Auth0 OIDC Discovery Contract
    auth0_domain = settings.auth0_domain.rstrip("/")
    oidc_data = _fetch_auth0_json(
        sess, f"{auth0_domain}/.well-known/openid-configuration", "OIDC discovery"
    )
    issuer = oidc_data.get("issuer", "") if isinstance(oidc_data, dict) else ""
    if not isinstance(issuer, str) or auth0_domain not in issuer:
        raise HealthCheckError(
            f"🔴 [Auth0 Down] Auth0 OIDC discovery endpoint returned unexpected issuer "
            f"'{issuer}'. {_AUTH0_IMPACT}"
        )

    # 2. Auth0 JWKS Endpoint Contract
    jwks_data = _fetch_auth0_json(sess, f"{auth0_domain}/.well-known/jwks.json", "JWKS")
    keys = jwks_data.get("keys") if isinstance(jwks_data, dict) else None
    if not isinstance(keys, list) or not keys:
        raise HealthCheckError(
            f"🔴 [Auth0 Down] Auth0 JWKS endpoint did not return any signing keys. {_AUTH0_IMPACT}"
        )

    # 3. Internal API Connectivity Probe
    internal_url = f"{settings.internal_api_url.rstrip('/')}/thermostats"
    m2m_headers = {"X-M2M-Token": settings.m2m_token}
    try:
        internal_resp = sess.get(internal_url, headers=m2m_headers, timeout=10)
    except requests.RequestException as err:
        raise HealthCheckError(
            f"🔴 [Internal API Down] Failed to connect to Internal API at "
            f"{settings.internal_api_url}: {describe_error(err)}."
        ) from err

    if internal_resp.status_code in (401, 403):
        raise HealthCheckError(
            "🔴 [M2M Auth Failed] Internal API rejected X-M2M-Token on /thermostats. "
            "Check M2M_TOKEN secret.",
            status_code=internal_resp.status_code,
        )

    if internal_resp.status_code != 200:
        detail = response_detail(internal_resp)
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
