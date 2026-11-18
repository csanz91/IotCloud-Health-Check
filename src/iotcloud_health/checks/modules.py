"""Thermostat automations and actuation pipeline health check."""

from __future__ import annotations

import logging
import time
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

logger = logging.getLogger("iotcloud_health.checks.modules")


def _read_setpoint(snapshot: Any) -> float:
    """Extracts the numeric setpoint from a snapshot payload; raises ValueError if absent."""
    if not isinstance(snapshot, dict):
        raise ValueError(f"snapshot is not an object: {snapshot!r}")
    value = snapshot.get("setpoint")
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"snapshot has no numeric setpoint: {value!r}")
    return float(value)


@check_service("thermostat")
def check_thermostat(
    sensor_id: str | None = None,
    session: requests.Session | None = None,
    wait_delay: float = 2.5,
) -> dict[str, Any]:
    """Ensures thermostat discovery is healthy and actuation roundtrips to Redis snapshot."""
    sess = session or get_session()
    base_url = settings.internal_api_url.rstrip("/")
    m2m_headers = {"X-M2M-Token": settings.m2m_token}
    json_headers = {"X-M2M-Token": settings.m2m_token, "Content-Type": "application/json"}
    target_sensor = sensor_id or settings.thermostat_sensor_id

    # --- Step A: Thermostat Discovery Contract ---
    discovery_url = f"{base_url}/thermostats"
    try:
        disc_resp = sess.get(discovery_url, headers=m2m_headers, timeout=15)
    except requests.RequestException as err:
        raise HealthCheckError(
            f"🔴 [Thermostat Discovery Failed] GET /thermostats connection failed: "
            f"{describe_error(err)}. "
            "Automation Runner cannot discover climate controllers."
        ) from err

    if disc_resp.status_code != 200:
        detail = response_detail(disc_resp)
        raise HealthCheckError(
            f"🔴 [Thermostat Discovery Failed] GET /thermostats returned HTTP "
            f"{disc_resp.status_code}: {detail}. Automation Runner cannot discover "
            "climate controllers.",
            status_code=disc_resp.status_code,
            detail=detail,
        )

    try:
        thermostats = disc_resp.json()
    except ValueError:
        thermostats = None
    if not isinstance(thermostats, list):
        raise HealthCheckError(
            "🔴 [Thermostat Discovery Failed] GET /thermostats returned invalid payload: "
            f"{response_detail(disc_resp)}. Automation Runner cannot discover climate controllers."
        )

    logger.debug("Discovered %d thermostats", len(thermostats))

    # --- Step B: Actuation & Redis Snapshot Roundtrip ---
    # 1. Query initial snapshot
    snapshot_url = f"{base_url}/sensors/{target_sensor}/snapshot"
    try:
        snap_resp = sess.get(snapshot_url, headers=m2m_headers, timeout=15)
    except requests.RequestException as err:
        raise HealthCheckError(
            f"🔴 [Action Dispatch Error] Failed to query initial snapshot on "
            f"/sensors/{target_sensor}/snapshot: {describe_error(err)}."
        ) from err

    if snap_resp.status_code != 200:
        detail = response_detail(snap_resp)
        raise HealthCheckError(
            "🔴 [Action Dispatch Error] Failed to get initial snapshot on "
            f"/sensors/{target_sensor}/snapshot: HTTP {snap_resp.status_code} - {detail}.",
            status_code=snap_resp.status_code,
            detail=detail,
        )

    try:
        init_snapshot = snap_resp.json()
        # A missing/null setpoint (fresh device, flushed Redis) is "unknown": dispatch
        # 22.0 anyway so the roundtrip itself repopulates it. Only malformed data fails.
        if isinstance(init_snapshot, dict) and init_snapshot.get("setpoint") is None:
            current_setpoint = 0.0
        else:
            current_setpoint = _read_setpoint(init_snapshot)
    except ValueError as err:
        raise HealthCheckError(
            f"🔴 [Action Dispatch Error] Initial snapshot on /sensors/{target_sensor}/snapshot "
            f"is invalid: {response_detail(snap_resp)}."
        ) from err

    # The demo device is a virtual device run by automation_runner. If it is offline,
    # say so instead of reporting a confusing actuation failure.
    if isinstance(init_snapshot, dict) and init_snapshot.get("online") is False:
        reason = init_snapshot.get("error") or "device status is not 'online'"
        raise HealthCheckError(
            f"🔴 [Demo Device Offline] '{target_sensor}' is offline ({reason}). The virtual "
            "device runtime in automation_runner is down or disconnected from EMQX."
        )

    # 2. Determine target setpoint: toggle between 22.0 and 21.5
    target_setpoint = 21.5 if abs(current_setpoint - 22.0) < 0.05 else 22.0

    # 3. Dispatch setpoint action
    action_url = f"{base_url}/sensors/{target_sensor}/actions/setpoint?user_id=health_check"
    action_payload = {
        "setpoint": target_setpoint,
        "source": "health_check",
    }
    try:
        act_resp = sess.post(action_url, json=action_payload, headers=json_headers, timeout=15)
    except requests.RequestException as err:
        raise HealthCheckError(
            f"🔴 [Action Dispatch Error] Failed to set setpoint on "
            f"/sensors/{target_sensor}/actions/setpoint: {describe_error(err)}."
        ) from err

    if act_resp.status_code != 200:
        detail = response_detail(act_resp)
        raise HealthCheckError(
            "🔴 [Action Dispatch Error] Failed to set setpoint on "
            f"/sensors/{target_sensor}/actions/setpoint: HTTP {act_resp.status_code} - {detail}.",
            status_code=act_resp.status_code,
            detail=detail,
        )

    # 4. Verify actuation reflection in Redis snapshot within 5 seconds
    new_snapshot: dict[str, Any] = {}
    reflected = False
    start_time = time.monotonic()

    # Poll / wait up to 5.0 seconds
    while time.monotonic() - start_time < 5.0:
        if wait_delay > 0:
            time.sleep(min(wait_delay, 2.5))
        try:
            snap_resp_new = sess.get(snapshot_url, headers=m2m_headers, timeout=15)
            if snap_resp_new.status_code == 200:
                new_snapshot = snap_resp_new.json()
                if abs(_read_setpoint(new_snapshot) - target_setpoint) < 0.05:
                    reflected = True
                    break
        except (requests.RequestException, ValueError) as err:
            logger.debug("Snapshot poll for '%s' not usable yet: %s", target_sensor, err)

        if wait_delay <= 0:
            break

    if not reflected:
        current_sp_reported = new_snapshot.get("setpoint", current_setpoint)
        raise HealthCheckError(
            f"🔴 [Automation Actuation Failure] Setpoint command ({target_setpoint}) was sent, "
            f"but Redis snapshot still reports {current_sp_reported} after 5s. "
            "Path: Internal API → Redis 'iotcloud:actions' → Rust Gateway → EMQX → "
            "automation_runner virtual device → EMQX → Rust Gateway → Redis."
        )

    logger.info(
        "Thermostat check healthy for '%s': setpoint updated from %s to %s",
        target_sensor,
        current_setpoint,
        target_setpoint,
    )
    return new_snapshot
