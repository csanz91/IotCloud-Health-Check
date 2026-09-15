from typing import Any
from unittest.mock import MagicMock, patch

import requests

from iotcloud_health.checker import check_service
from iotcloud_health.checks.public_api import check_public_api
from iotcloud_health.notifier import TelegramNotifier


def get_wrapped(func: Any):
    return getattr(func, "__wrapped__", func)


def test_check_public_api_success():
    session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "healthy"}
    session.get.return_value = mock_resp

    with patch("iotcloud_health.checks.public_api.get_ssl_days_remaining", return_value=45):
        result = check_public_api("https://api.dev.iotcloud.es/api/v2/health", session=session)
        assert result is not None
        assert result["status_code"] == 200
        assert result["ssl_days_remaining"] == 45


def test_check_public_api_ssl_expired():
    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call
    decorated = check_service("public_api", notifier=notifier)(get_wrapped(check_public_api))

    with patch("iotcloud_health.checks.public_api.get_ssl_days_remaining", return_value=-1):
        result = decorated("https://api.dev.iotcloud.es/api/v2/health")
        assert result is None
        assert len(mock_notif_calls) == 1
        name, healthy, msg = mock_notif_calls[0]
        assert name == "public_api"
        assert healthy is False
        assert "🔴 [Public SSL Expired]" in msg


def test_check_public_api_ssl_expiring_soon():
    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call
    decorated = check_service("public_api", notifier=notifier)(get_wrapped(check_public_api))

    with patch("iotcloud_health.checks.public_api.get_ssl_days_remaining", return_value=3):
        result = decorated("https://api.dev.iotcloud.es/api/v2/health")
        assert result is None
        assert len(mock_notif_calls) == 1
        _, healthy, msg = mock_notif_calls[0]
        assert healthy is False
        assert "🔴 [Public SSL Expiring Soon]" in msg


def test_check_public_api_connection_failure():
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = requests.ConnectionError("Failed to resolve")

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call
    decorated = check_service("public_api", notifier=notifier)(get_wrapped(check_public_api))

    with patch("iotcloud_health.checks.public_api.get_ssl_days_remaining", return_value=30):
        result = decorated("https://api.dev.iotcloud.es/api/v2/health", session=session)
        assert result is None
        assert len(mock_notif_calls) == 1
        _, healthy, msg = mock_notif_calls[0]
        assert healthy is False
        assert "🔴 [Public API Down]" in msg


def test_check_public_api_http_error():
    session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_resp.text = "Bad Gateway"
    session.get.return_value = mock_resp

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call
    decorated = check_service("public_api", notifier=notifier)(get_wrapped(check_public_api))

    with patch("iotcloud_health.checks.public_api.get_ssl_days_remaining", return_value=30):
        result = decorated("https://api.dev.iotcloud.es/api/v2/health", session=session)
        assert result is None
        assert len(mock_notif_calls) == 1
        _, healthy, msg = mock_notif_calls[0]
        assert healthy is False
        assert "🔴 [Public API Error]" in msg


def test_check_public_api_unhealthy_status():
    session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "degraded"}
    session.get.return_value = mock_resp

    notifier = MagicMock(spec=TelegramNotifier)
    mock_notif_calls = []

    def record_call(name, healthy, failure_message="", **kw):
        mock_notif_calls.append((name, healthy, failure_message))

    notifier.report_check.side_effect = record_call
    decorated = check_service("public_api", notifier=notifier)(get_wrapped(check_public_api))

    with patch("iotcloud_health.checks.public_api.get_ssl_days_remaining", return_value=30):
        result = decorated("https://api.dev.iotcloud.es/api/v2/health", session=session)
        assert result is None
        assert len(mock_notif_calls) == 1
        _, healthy, msg = mock_notif_calls[0]
        assert healthy is False
        assert "🔴 [Public API Unhealthy]" in msg
