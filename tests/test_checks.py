from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import requests

from iotcloud_health.checker import check_service
from iotcloud_health.checks.api import check_api
from iotcloud_health.checks.data_storage import check_ingestion
from iotcloud_health.checks.modules import check_thermostat
from iotcloud_health.notifier import TelegramNotifier

if TYPE_CHECKING:
    from collections.abc import Callable


def get_wrapped(func: Any) -> Callable[..., Any]:
    return getattr(func, "__wrapped__", func)



# ==========================================
# Check 1: Ingestion & TimescaleDB Tests
# ==========================================


def test_check_ingestion_success():
    session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    mock_resp.json.return_value = {
        "sensor_id": "demo_thermostat",
        "data": [
            [21.6, now_ms - 60000],  # 1 min ago
            [21.5, now_ms - 300000],  # 5 min ago
        ],
    }
    session.post.return_value = mock_resp

    data = check_ingestion("demo_thermostat", session=session)
    assert data is not None
    assert len(data) == 2
    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert "/sensors/demo_thermostat/data" in args[0]
    assert "X-M2M-Token" in kwargs["headers"]


def test_check_ingestion_auth_failure():
    session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    session.post.return_value = mock_resp

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call

    decorated = check_service("ingestion", notifier=notifier)(get_wrapped(check_ingestion))
    result = decorated("demo_thermostat", session=session)

    assert result is None
    assert len(mock_notif_calls) == 1
    name, healthy, msg = mock_notif_calls[0]
    assert name == "ingestion"
    assert healthy is False
    assert "🔴 [M2M Auth Failed]" in msg


def test_check_ingestion_no_data_returned():
    session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"sensor_id": "demo_thermostat", "data": []}
    session.post.return_value = mock_resp

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call

    decorated = check_service("ingestion", notifier=notifier)(get_wrapped(check_ingestion))
    result = decorated("demo_thermostat", session=session)

    assert result is None
    assert len(mock_notif_calls) == 1
    _, healthy, msg = mock_notif_calls[0]
    assert healthy is False
    assert "🔴 [Ingestion Pipeline Failed] 0 readings recorded in TimescaleDB" in msg


def test_check_ingestion_stale_data():
    session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    # Data from 20 minutes ago (> 15 min / 900s threshold)
    stale_ms = int((datetime.now(UTC).timestamp() - 1200) * 1000)
    mock_resp.json.return_value = {
        "sensor_id": "demo_thermostat",
        "data": [[20.0, stale_ms]],
    }
    session.post.return_value = mock_resp

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call

    decorated = check_service("ingestion", notifier=notifier)(get_wrapped(check_ingestion))
    result = decorated("demo_thermostat", session=session)

    assert result is None
    assert len(mock_notif_calls) == 1
    _, healthy, msg = mock_notif_calls[0]
    assert healthy is False
    assert "🔴 [Ingestion Stalled] Telemetry for 'demo_thermostat' is stale." in msg


def test_check_ingestion_db_error():
    session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error: Timescale connection refused"
    session.post.return_value = mock_resp

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call

    decorated = check_service("ingestion", notifier=notifier)(get_wrapped(check_ingestion))
    result = decorated("demo_thermostat", session=session)

    assert result is None
    assert len(mock_notif_calls) == 1
    _, healthy, msg = mock_notif_calls[0]
    assert healthy is False
    assert "🔴 [Database Error] TimescaleDB query failed with HTTP 500" in msg


# ==========================================
# Check 2: Thermostat Discovery & Actuation Tests
# ==========================================


def test_check_thermostat_success_toggle_setpoint():
    session = MagicMock(spec=requests.Session)

    # 1. Discovery response
    disc_resp = MagicMock()
    disc_resp.status_code = 200
    disc_resp.json.return_value = [{"sensorId": "demo_thermostat", "sensorName": "Termostato"}]

    # 2. Initial snapshot (setpoint 22.0)
    snap_init_resp = MagicMock()
    snap_init_resp.status_code = 200
    snap_init_resp.json.return_value = {
        "sensorId": "demo_thermostat",
        "setpoint": 22.0,
        "value": 21.0,
    }

    # 3. Action response
    act_resp = MagicMock()
    act_resp.status_code = 200
    act_resp.json.return_value = {"success": True, "message": "Setpoint set successfully"}

    # 4. Updated snapshot reflection (setpoint updated to 21.5)
    snap_new_resp = MagicMock()
    snap_new_resp.status_code = 200
    snap_new_resp.json.return_value = {
        "sensorId": "demo_thermostat",
        "setpoint": 21.5,
        "value": 21.0,
    }

    def get_side_effect(url, **kwargs):
        if "/thermostats" in url:
            return disc_resp
        if "/snapshot" in url:
            # First snapshot returns 22.0, second returns 21.5
            if session.post.called:
                return snap_new_resp
            return snap_init_resp
        return disc_resp

    session.get.side_effect = get_side_effect
    session.post.return_value = act_resp

    result = check_thermostat("demo_thermostat", session=session, wait_delay=0)
    assert result is not None
    assert result["setpoint"] == 21.5

    # Check that post was called with 21.5
    assert session.post.call_count == 1
    _, kwargs_post = session.post.call_args
    assert kwargs_post["json"]["setpoint"] == 21.5


def test_check_thermostat_discovery_failure():
    session = MagicMock(spec=requests.Session)
    disc_resp = MagicMock()
    disc_resp.status_code = 502
    disc_resp.text = "Bad Gateway"
    session.get.return_value = disc_resp

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call

    decorated = check_service("thermostat", notifier=notifier)(get_wrapped(check_thermostat))
    result = decorated("demo_thermostat", session=session, wait_delay=0)

    assert result is None
    assert len(mock_notif_calls) == 1
    name, healthy, msg = mock_notif_calls[0]
    assert name == "thermostat"
    assert healthy is False
    assert "🔴 [Thermostat Discovery Failed] GET /thermostats returned HTTP 502" in msg


def test_check_thermostat_action_failure():
    session = MagicMock(spec=requests.Session)

    disc_resp = MagicMock()
    disc_resp.status_code = 200
    disc_resp.json.return_value = []

    snap_resp = MagicMock()
    snap_resp.status_code = 200
    snap_resp.json.return_value = {"setpoint": 21.5}

    session.get.side_effect = [disc_resp, snap_resp]

    act_resp = MagicMock()
    act_resp.status_code = 400
    act_resp.text = "Invalid target setpoint"
    session.post.return_value = act_resp

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call

    decorated = check_service("thermostat", notifier=notifier)(get_wrapped(check_thermostat))
    result = decorated("demo_thermostat", session=session, wait_delay=0)

    assert result is None
    assert len(mock_notif_calls) == 1
    _, healthy, msg = mock_notif_calls[0]
    assert healthy is False
    assert (
        "🔴 [Action Dispatch Error] Failed to set setpoint on "
        "/sensors/demo_thermostat/actions/setpoint: HTTP 400"
    ) in msg


def test_check_thermostat_actuation_not_reflected():
    session = MagicMock(spec=requests.Session)

    disc_resp = MagicMock()
    disc_resp.status_code = 200
    disc_resp.json.return_value = [{"sensorId": "demo_thermostat"}]

    # Snapshot returns 22.0 both before and after action
    snap_resp = MagicMock()
    snap_resp.status_code = 200
    snap_resp.json.return_value = {"setpoint": 22.0}

    def get_side_effect(url, **kwargs):
        if "/thermostats" in url:
            return disc_resp
        return snap_resp

    session.get.side_effect = get_side_effect

    act_resp = MagicMock()
    act_resp.status_code = 200
    act_resp.json.return_value = {"success": True}
    session.post.return_value = act_resp

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call

    decorated = check_service("thermostat", notifier=notifier)(get_wrapped(check_thermostat))
    result = decorated("demo_thermostat", session=session, wait_delay=0)

    assert result is None
    assert len(mock_notif_calls) == 1
    _, healthy, msg = mock_notif_calls[0]
    assert healthy is False
    assert (
        "🔴 [Automation Actuation Failure] Setpoint command (21.5) was sent, "
        "but Redis snapshot still reports 22.0 after 5s."
    ) in msg


# ==========================================
# Check 3: Auth0 OIDC & Internal API Tests
# ==========================================


def test_check_api_success():
    session = MagicMock(spec=requests.Session)

    oidc_resp = MagicMock()
    oidc_resp.status_code = 200
    oidc_resp.json.return_value = {"issuer": "https://iotauth.eu.auth0.com/"}

    jwks_resp = MagicMock()
    jwks_resp.status_code = 200
    jwks_resp.json.return_value = {"keys": [{"kty": "RSA", "kid": "key-1"}]}

    internal_resp = MagicMock()
    internal_resp.status_code = 200
    internal_resp.json.return_value = []

    def get_side_effect(url, **kwargs):
        if "openid-configuration" in url:
            return oidc_resp
        if "jwks.json" in url:
            return jwks_resp
        if "/thermostats" in url:
            return internal_resp
        return MagicMock(status_code=200)

    session.get.side_effect = get_side_effect

    result = check_api(session=session)
    assert result is not None
    assert result["auth0_issuer"] == "https://iotauth.eu.auth0.com/"
    assert result["jwks_keys_count"] == 1


def test_check_api_auth0_down():
    session = MagicMock(spec=requests.Session)
    oidc_resp = MagicMock()
    oidc_resp.status_code = 503
    oidc_resp.text = "Service Unavailable"
    session.get.return_value = oidc_resp

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call

    decorated = check_service("api", notifier=notifier)(get_wrapped(check_api))
    result = decorated(session=session)

    assert result is None
    assert len(mock_notif_calls) == 1
    name, healthy, msg = mock_notif_calls[0]
    assert name == "api"
    assert healthy is False
    assert (
        "🔴 [Auth0 Down] Auth0 OIDC discovery endpoint is unreachable or returning HTTP 503"
    ) in msg


def test_check_api_internal_m2m_rejected():
    session = MagicMock(spec=requests.Session)

    oidc_resp = MagicMock()
    oidc_resp.status_code = 200
    oidc_resp.json.return_value = {"issuer": "https://iotauth.eu.auth0.com/"}

    jwks_resp = MagicMock()
    jwks_resp.status_code = 200
    jwks_resp.json.return_value = {"keys": []}

    internal_resp = MagicMock()
    internal_resp.status_code = 401
    internal_resp.text = "Invalid X-M2M-Token"

    def get_side_effect(url, **kwargs):
        if "openid-configuration" in url:
            return oidc_resp
        if "jwks.json" in url:
            return jwks_resp
        if "/thermostats" in url:
            return internal_resp
        return MagicMock(status_code=200)

    session.get.side_effect = get_side_effect

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call

    decorated = check_service("api", notifier=notifier)(get_wrapped(check_api))
    result = decorated(session=session)

    assert result is None
    assert len(mock_notif_calls) == 1
    _, healthy, msg = mock_notif_calls[0]
    assert healthy is False
    assert "🔴 [M2M Auth Failed] Internal API rejected X-M2M-Token on /thermostats." in msg




