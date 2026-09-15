from typing import Any
from unittest.mock import MagicMock, patch

from iotcloud_health.checker import check_service
from iotcloud_health.checks.mqtt import check_mqtt_wss
from iotcloud_health.notifier import TelegramNotifier


def get_wrapped(func: Any):
    return getattr(func, "__wrapped__", func)


def test_check_mqtt_wss_success():
    mock_sock = MagicMock()
    mock_sock.recv.return_value = (
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Protocol: mqtt\r\n\r\n"
    )

    with (
        patch("iotcloud_health.checks.mqtt.get_ssl_days_remaining", return_value=60),
        patch("socket.create_connection", return_value=MagicMock()),
        patch("ssl.create_default_context") as mock_ctx,
    ):
        mock_ctx.return_value.wrap_socket.return_value = mock_sock
        result = check_mqtt_wss("wss://mqtt.iotcloud.es/mqtt")
        assert result is not None
        assert result["status"] == 101
        assert result["ssl_days_remaining"] == 60


def test_check_mqtt_wss_ssl_expired():
    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call
    decorated = check_service("mqtt_wss", notifier=notifier)(get_wrapped(check_mqtt_wss))

    with patch("iotcloud_health.checks.mqtt.get_ssl_days_remaining", return_value=-1):
        result = decorated("wss://mqtt.iotcloud.es/mqtt")
        assert result is None
        assert len(mock_notif_calls) == 1
        name, healthy, msg = mock_notif_calls[0]
        assert name == "mqtt_wss"
        assert healthy is False
        assert "🔴 [MQTT SSL Expired]" in msg


def test_check_mqtt_wss_ssl_expiring_soon():
    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call
    decorated = check_service("mqtt_wss", notifier=notifier)(get_wrapped(check_mqtt_wss))

    with patch("iotcloud_health.checks.mqtt.get_ssl_days_remaining", return_value=4):
        result = decorated("wss://mqtt.iotcloud.es/mqtt")
        assert result is None
        assert len(mock_notif_calls) == 1
        _, healthy, msg = mock_notif_calls[0]
        assert healthy is False
        assert "🔴 [MQTT SSL Expiring Soon]" in msg


def test_check_mqtt_wss_connection_failure():
    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call
    decorated = check_service("mqtt_wss", notifier=notifier)(get_wrapped(check_mqtt_wss))

    with (
        patch("iotcloud_health.checks.mqtt.get_ssl_days_remaining", return_value=30),
        patch("socket.create_connection", side_effect=OSError("Connection refused")),
    ):
        result = decorated("wss://mqtt.iotcloud.es/mqtt")
        assert result is None
        assert len(mock_notif_calls) == 1
        _, healthy, msg = mock_notif_calls[0]
        assert healthy is False
        assert "🔴 [MQTT WSS Down]" in msg


def test_check_mqtt_wss_status_not_101():
    mock_sock = MagicMock()
    mock_sock.recv.return_value = b"HTTP/1.1 502 Bad Gateway\r\n\r\n"

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call
    decorated = check_service("mqtt_wss", notifier=notifier)(get_wrapped(check_mqtt_wss))

    with (
        patch("iotcloud_health.checks.mqtt.get_ssl_days_remaining", return_value=30),
        patch("socket.create_connection", return_value=MagicMock()),
        patch("ssl.create_default_context") as mock_ctx,
    ):
        mock_ctx.return_value.wrap_socket.return_value = mock_sock
        result = decorated("wss://mqtt.iotcloud.es/mqtt")
        assert result is None
        assert len(mock_notif_calls) == 1
        _, healthy, msg = mock_notif_calls[0]
        assert healthy is False
        assert "🔴 [MQTT WSS Handshake Failed]" in msg


def test_check_mqtt_wss_missing_protocol_header():
    mock_sock = MagicMock()
    mock_sock.recv.return_value = (
        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
    )

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call
    decorated = check_service("mqtt_wss", notifier=notifier)(get_wrapped(check_mqtt_wss))

    with (
        patch("iotcloud_health.checks.mqtt.get_ssl_days_remaining", return_value=30),
        patch("socket.create_connection", return_value=MagicMock()),
        patch("ssl.create_default_context") as mock_ctx,
    ):
        mock_ctx.return_value.wrap_socket.return_value = mock_sock
        result = decorated("wss://mqtt.iotcloud.es/mqtt")
        assert result is None
        assert len(mock_notif_calls) == 1
        _, healthy, msg = mock_notif_calls[0]
        assert healthy is False
        assert "did not return 'Sec-WebSocket-Protocol: mqtt'" in msg
