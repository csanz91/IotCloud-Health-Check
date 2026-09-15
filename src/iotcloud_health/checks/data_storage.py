"""Data storage and ingestion pipeline health check."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from iotcloud_health.checker import HealthCheckError, check_service
from iotcloud_health.config import settings

logger = logging.getLogger("iotcloud_health.checks.data_storage")


@check_service("ingestion")
def check_ingestion(
    sensor_id: str | None = None,
    session: requests.Session | None = None,
) -> list[list[Any]]:
    """Verifies that the full ingestion pipeline writes time-series telemetry to TimescaleDB."""
    target_sensor = sensor_id or settings.thermostat_sensor_id
    sess = session or requests.Session()
    url = f"{settings.internal_api_url.rstrip('/')}/sensors/{target_sensor}/data"

    headers = {
        "X-M2M-Token": settings.m2m_token,
        "Content-Type": "application/json",
    }

    now_utc = datetime.now(UTC)
    from_dt = now_utc - timedelta(minutes=30)
    payload = {
        "from_timestamp": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to_timestamp": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_data_points": 50,
    }

    try:
        response = sess.post(url, json=payload, headers=headers, timeout=15)
    except requests.RequestException as err:
        raise HealthCheckError(
            f"🔴 [Database Error] TimescaleDB query failed: {err}."
        ) from err

    if response.status_code in (401, 403):
        raise HealthCheckError(
            f"🔴 [M2M Auth Failed] Internal API rejected X-M2M-Token on "
            f"/sensors/{target_sensor}/data. Check M2M_TOKEN secret.",
            status_code=response.status_code,
        )

    if response.status_code >= 500 or response.status_code != 200:
        detail = response.text
        raise HealthCheckError(
            f"🔴 [Database Error] TimescaleDB query failed with HTTP {response.status_code}: "
            f"{detail}.",
            status_code=response.status_code,
            detail=detail,
        )

    decoded = response.json()
    data: list[list[Any]] = decoded.get("data", [])

    if not data:
        raise HealthCheckError(
            "🔴 [Ingestion Pipeline Failed] 0 readings recorded in TimescaleDB for "
            f"sensor '{target_sensor}' in the last 30 minutes. Check if Rust Gateway "
            "or MQTT broker is down."
        )

    newest_ts_ms = max(point[1] for point in data)
    newest_dt = datetime.fromtimestamp(newest_ts_ms / 1000.0, tz=UTC)
    data_age_seconds = (now_utc - newest_dt).total_seconds()

    if data_age_seconds > 900:
        minutes_ago = round(data_age_seconds / 60)
        raise HealthCheckError(
            f"🔴 [Ingestion Stalled] Telemetry for '{target_sensor}' is stale. Latest point "
            f"recorded at {newest_dt.isoformat()} ({minutes_ago}m ago, threshold: 15m)."
        )

    logger.info(
        "Ingestion check healthy for '%s': %d points, newest %ds ago",
        target_sensor,
        len(data),
        int(data_age_seconds),
    )
    return data

