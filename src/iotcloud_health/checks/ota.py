"""OTA firmware server reachability check."""

from __future__ import annotations

import logging
import warnings
from typing import Any

import requests
from urllib3.exceptions import InsecureRequestWarning

from iotcloud_health.checker import HealthCheckError, check_service, describe_error, get_session
from iotcloud_health.config import settings

logger = logging.getLogger("iotcloud_health.checks.ota")


@check_service("ota")
def check_ota(url: str | None = None, session: requests.Session | None = None) -> dict[str, Any]:
    """Verifies nginx can reach the OTA static server.

    The OTA host uses a self-signed certificate that devices may pin, so the
    certificate is not verified. Any non-5xx answer (404 for a missing file is
    normal) proves the `ota` container is reachable; 5xx means nginx cannot
    reach it and devices cannot download firmware.
    """
    target_url = url or settings.ota_url
    sess = session or get_session()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            resp = sess.get(target_url, timeout=10, verify=False)
    except requests.RequestException as err:
        raise HealthCheckError(
            f"🔴 [OTA Down] Cannot reach the OTA server at {target_url}: {describe_error(err)}. "
            "Devices cannot download firmware updates."
        ) from err

    if resp.status_code >= 500:
        raise HealthCheckError(
            f"🔴 [OTA Down] {target_url} returned HTTP {resp.status_code}: nginx cannot "
            "reach the `ota` container. Devices cannot download firmware updates.",
            status_code=resp.status_code,
        )

    logger.info("OTA check passed (%s, HTTP %s)", target_url, resp.status_code)
    return {"url": target_url, "status_code": resp.status_code}
