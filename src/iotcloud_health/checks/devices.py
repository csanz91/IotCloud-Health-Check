"""Watched real devices online check.

Each watched sensor is reported as its own check (`device:<sensor_id>`), so one
device going offline does not hide another one going offline later.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import requests

from iotcloud_health.checker import (
    HealthCheckError,
    check_service,
    describe_error,
    get_session,
    response_detail,
)
from iotcloud_health.config import settings

if TYPE_CHECKING:
    from iotcloud_health.checker import CheckReporter

logger = logging.getLogger("iotcloud_health.checks.devices")

# sensor_id -> display name, resolved once per process
_name_cache: dict[str, str] = {}


def _fetch_snapshots(sensor_ids: list[str], sess: requests.Session) -> dict[str, dict[str, Any]]:
    url = f"{settings.internal_api_url.rstrip('/')}/sensors/snapshot"
    headers = {"X-M2M-Token": settings.m2m_token}
    try:
        resp = sess.post(url, json={"sensorIds": sensor_ids}, headers=headers, timeout=15)
    except requests.RequestException as err:
        raise HealthCheckError(
            f"🔴 [Device Status Unknown] POST /sensors/snapshot failed: {describe_error(err)}."
        ) from err
    if resp.status_code != 200:
        raise HealthCheckError(
            f"🔴 [Device Status Unknown] POST /sensors/snapshot returned HTTP "
            f"{resp.status_code}: {response_detail(resp)}.",
            status_code=resp.status_code,
        )
    try:
        return {item["sensorId"]: item for item in resp.json()}
    except (ValueError, KeyError, TypeError) as err:
        raise HealthCheckError(
            f"🔴 [Device Status Unknown] POST /sensors/snapshot returned an unexpected "
            f"payload: {response_detail(resp)}."
        ) from err


def _sensor_name(sensor_id: str, sess: requests.Session) -> str:
    if sensor_id not in _name_cache:
        url = f"{settings.internal_api_url.rstrip('/')}/sensors/{sensor_id}"
        try:
            resp = sess.get(url, headers={"X-M2M-Token": settings.m2m_token}, timeout=10)
            name = resp.json().get("sensorName") if resp.status_code == 200 else None
        except requests.RequestException, ValueError, AttributeError:
            return sensor_id  # Not cached: retry the lookup next time.
        _name_cache[sensor_id] = name or sensor_id
    return _name_cache[sensor_id]


def check_devices(
    sensor_ids: list[str] | None = None,
    session: requests.Session | None = None,
    notifier: CheckReporter | None = None,
) -> list[str] | None:
    """Alerts per watched sensor when its device reports offline.

    Returns the list of online sensor IDs, or None if any watched device is
    offline or the status query failed.
    """
    ids = sensor_ids if sensor_ids is not None else settings.watched_sensor_id_list
    if not ids:
        return []
    sess = session or get_session()

    snapshots = check_service("devices", notifier=notifier)(_fetch_snapshots)(ids, sess)
    if snapshots is None:
        return None

    if notifier is None:
        from iotcloud_health.notifier import default_notifier

        notifier = default_notifier

    online: list[str] = []
    for sensor_id in ids:
        snapshot = snapshots.get(sensor_id)
        if snapshot is not None and snapshot.get("online") is True:
            notifier.report_check(
                f"device:{sensor_id}", healthy=True, display_name=_name_cache.get(sensor_id)
            )
            online.append(sensor_id)
            continue

        name = None
        if snapshot is None:
            message = (
                f"🔴 [Device Unknown] Watched sensor '{sensor_id}' was not found or has no "
                "device/location. Check WATCHED_SENSOR_IDS."
            )
        else:
            name = _sensor_name(sensor_id, sess)
            message = (
                f"🔴 [Device Offline] {name} ({sensor_id}) is offline: its device's MQTT "
                "status is not 'online' (power loss, Wi-Fi, brownout or reboot loop)."
            )
        logger.warning(message)
        notifier.report_check(
            f"device:{sensor_id}", healthy=False, failure_message=message, display_name=name
        )

    if len(online) < len(ids):
        return None
    logger.info("Device check passed: %d watched devices online", len(ids))
    return online
