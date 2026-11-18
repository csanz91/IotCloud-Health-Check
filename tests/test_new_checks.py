"""Tests for the MQTT device login, OTA and watched-devices checks."""

from __future__ import annotations

import socket
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from iotcloud_health.checker import check_service
from iotcloud_health.checks import devices as devices_module
from iotcloud_health.checks import mqtt_device
from iotcloud_health.checks.devices import check_devices
from iotcloud_health.checks.modules import check_thermostat
from iotcloud_health.checks.mqtt_device import (
    _encode_length,
    _read_packet,
    check_mqtt_device_login,
)
from iotcloud_health.checks.ota import check_ota


def get_wrapped(func: Any):
    return getattr(func, "__wrapped__", func)


class RecordingReporter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, str]] = []

    def report_check(
        self,
        check_name: str,
        healthy: bool,
        failure_message: str = "",
        *,
        display_name: str | None = None,
    ) -> bool:
        self.calls.append((check_name, healthy, failure_message))
        return False


def _token_session(token: str = "device.jwt.token") -> MagicMock:
    session = MagicMock(spec=requests.Session)
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"token": token, "role": "Device"}
    session.get.return_value = resp
    return session


class FakeBroker:
    """Single-connection MQTT broker that answers CONNECT and SUBSCRIBE."""

    def __init__(self, connack_rc: int = 0, suback_rc: int = 0, send_retained: bool = True):
        self.connack_rc = connack_rc
        self.suback_rc = suback_rc
        self.send_retained = send_retained
        self.received: list[tuple[int, bytes]] = []
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        conn, _ = self.server.accept()
        with conn:
            conn.settimeout(5)
            try:
                ptype, body = _read_packet(conn)
                self.received.append((ptype, body))
                conn.sendall(bytes([0x20, 0x02, 0x00, self.connack_rc]))
                if self.connack_rc:
                    return
                ptype, body = _read_packet(conn)
                self.received.append((ptype, body))
                if self.send_retained:
                    payload = b"\x00\x05topic21.5"
                    conn.sendall(bytes([0x31]) + _encode_length(len(payload)) + payload)
                conn.sendall(bytes([0x90, 0x03]) + body[:2] + bytes([self.suback_rc]))
                ptype, body = _read_packet(conn)
                self.received.append((ptype, body))
            except OSError, ConnectionError:
                pass

    def close(self) -> None:
        self.thread.join(timeout=5)
        self.server.close()


@pytest.fixture(autouse=True)
def clear_caches():
    mqtt_device._token_cache.clear()
    devices_module._name_cache.clear()
    yield


# ---------------- MQTT device login ----------------


def test_encode_length_handles_multibyte_lengths():
    assert _encode_length(0) == b"\x00"
    assert _encode_length(127) == b"\x7f"
    assert _encode_length(128) == b"\x80\x01"
    assert _encode_length(321) == b"\xc1\x02"


def test_mqtt_device_login_success_uses_token_and_unique_client_id():
    token = "x" * 300  # long token forces a multi-byte remaining length
    broker = FakeBroker()
    try:
        result = get_wrapped(check_mqtt_device_login)(
            host="127.0.0.1", port=broker.port, session=_token_session(token)
        )
    finally:
        broker.close()

    assert result["device_id"] == "demo_virtual_hub_01"
    connect_body = broker.received[0][1]
    assert broker.received[0][0] == 1
    assert token.encode() in connect_body
    assert b"iotcloud-healthcheck-" in connect_body
    assert broker.received[1][0] == 8  # SUBSCRIBE
    assert (
        b"v1/5d0000000000000000000001/demo_virtual_hub_01/demo_thermostat"
        in (broker.received[1][1])
    )
    assert broker.received[2][0] == 14  # DISCONNECT


def test_mqtt_device_login_reports_authn_rejection():
    broker = FakeBroker(connack_rc=5)
    reporter = RecordingReporter()
    decorated = check_service("mqtt_device", notifier=reporter)(
        get_wrapped(check_mqtt_device_login)
    )
    try:
        assert decorated(host="127.0.0.1", port=broker.port, session=_token_session()) is None
    finally:
        broker.close()
    [(_, healthy, msg)] = reporter.calls
    assert healthy is False
    assert "not authorized" in msg and "authn" in msg


def test_mqtt_device_login_reports_authz_denial():
    broker = FakeBroker(suback_rc=0x80, send_retained=False)
    reporter = RecordingReporter()
    decorated = check_service("mqtt_device", notifier=reporter)(
        get_wrapped(check_mqtt_device_login)
    )
    try:
        assert decorated(host="127.0.0.1", port=broker.port, session=_token_session()) is None
    finally:
        broker.close()
    assert "authz" in reporter.calls[0][2]


def test_mqtt_device_login_reports_closed_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing listening

    reporter = RecordingReporter()
    decorated = check_service("mqtt_device", notifier=reporter)(
        get_wrapped(check_mqtt_device_login)
    )
    assert decorated(host="127.0.0.1", port=port, session=_token_session()) is None
    assert "Cannot open TCP" in reporter.calls[0][2]


def test_mqtt_device_token_is_cached_between_runs():
    session = _token_session()
    for _ in range(2):
        broker = FakeBroker(send_retained=False)
        try:
            get_wrapped(check_mqtt_device_login)(
                host="127.0.0.1", port=broker.port, session=session
            )
        finally:
            broker.close()
    assert session.get.call_count == 1


# ---------------- OTA ----------------


@pytest.mark.parametrize("status", [200, 403, 404])
def test_ota_non_5xx_is_up(status):
    session = MagicMock(spec=requests.Session)
    session.get.return_value = MagicMock(status_code=status)
    result = get_wrapped(check_ota)(url="https://ota.example/", session=session)
    assert result["status_code"] == status
    assert session.get.call_args.kwargs["verify"] is False


def test_ota_502_is_down():
    session = MagicMock(spec=requests.Session)
    session.get.return_value = MagicMock(status_code=502)
    reporter = RecordingReporter()
    decorated = check_service("ota", notifier=reporter)(get_wrapped(check_ota))
    assert decorated(url="https://ota.example/", session=session) is None
    assert "[OTA Down]" in reporter.calls[0][2]


# ---------------- Watched devices ----------------


def _snapshot_session(items: list[dict[str, Any]], names: dict[str, str] | None = None):
    session = MagicMock(spec=requests.Session)
    snap = MagicMock(status_code=200)
    snap.json.return_value = items
    session.post.return_value = snap

    def get(url, **kwargs):
        sensor_id = url.rsplit("/", 1)[-1]
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"sensorName": (names or {}).get(sensor_id)}
        return resp

    session.get.side_effect = get
    return session


def test_devices_reports_each_sensor_separately():
    session = _snapshot_session(
        [
            {"sensorId": "a", "online": True},
            {"sensorId": "b", "online": False},
        ],
        names={"b": "Habitaciones"},
    )
    reporter = RecordingReporter()
    assert check_devices(["a", "b", "missing"], session=session, notifier=reporter) is None

    by_name = {name: (healthy, msg) for name, healthy, msg in reporter.calls}
    assert by_name["devices"] == (True, "")
    assert by_name["device:a"] == (True, "")
    assert by_name["device:b"][0] is False
    assert "Habitaciones (b) is offline" in by_name["device:b"][1]
    assert "[Device Unknown]" in by_name["device:missing"][1]
    assert session.post.call_args.kwargs["json"] == {"sensorIds": ["a", "b", "missing"]}


def test_devices_all_online_returns_ids():
    session = _snapshot_session([{"sensorId": "a", "online": True}])
    reporter = RecordingReporter()
    assert check_devices(["a"], session=session, notifier=reporter) == ["a"]


def test_devices_without_watch_list_is_a_noop():
    session = MagicMock(spec=requests.Session)
    assert check_devices([], session=session, notifier=RecordingReporter()) == []
    session.post.assert_not_called()


def test_devices_api_failure_reports_devices_check_only():
    session = MagicMock(spec=requests.Session)
    session.post.return_value = MagicMock(status_code=503, text="down")
    reporter = RecordingReporter()
    assert check_devices(["a"], session=session, notifier=reporter) is None
    [(name, healthy, msg)] = reporter.calls
    assert name == "devices" and healthy is False
    assert "HTTP 503" in msg


# ---------------- Thermostat: demo device offline ----------------


def test_thermostat_reports_offline_demo_device_without_dispatching():
    session = MagicMock(spec=requests.Session)
    disc = MagicMock(status_code=200)
    disc.json.return_value = []
    snap = MagicMock(status_code=200)
    snap.json.return_value = {"setpoint": 21.5, "online": False, "error": None}
    session.get.side_effect = [disc, snap]

    reporter = RecordingReporter()
    decorated = check_service("thermostat", notifier=reporter)(get_wrapped(check_thermostat))
    assert decorated("demo_thermostat", session=session, wait_delay=0) is None
    msg = reporter.calls[0][2]
    assert "[Demo Device Offline]" in msg and "automation_runner" in msg
    session.post.assert_not_called()
