"""Tests for Telegram notification dispatching."""

from unittest.mock import MagicMock

import requests

from iotcloud_health.notifier import TelegramNotifier


def test_telegram_notifier_success():
    session = MagicMock(spec=requests.Session)
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    session.post.return_value = mock_response

    notifier = TelegramNotifier(token="test-token", chat_id=12345, session=session)
    result = notifier.send_notification("Service is working")

    assert result is True
    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert "https://api.telegram.org/bottest-token/sendMessage" in args[0]
    assert kwargs["json"]["chat_id"] == 12345
    assert kwargs["json"]["text"] == "[IotCloud]: Service is working"
    assert kwargs["json"]["parse_mode"] == "markdown"


def test_telegram_notifier_failure():
    session = MagicMock(spec=requests.Session)
    session.post.side_effect = requests.RequestException("Network error")

    notifier = TelegramNotifier(token="test-token", chat_id=12345, session=session)
    result = notifier.send_notification("Service failed")

    assert result is False


def test_telegram_notifier_state_transitions():
    session = MagicMock(spec=requests.Session)
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    session.post.return_value = mock_response

    notifier = TelegramNotifier(token="test-token", chat_id=12345, session=session)

    # 1. Initial healthy run -> state recorded as HEALTHY, no alert sent
    res1 = notifier.report_check("ingestion", healthy=True)
    assert res1 is False
    assert notifier.states["ingestion"] == "HEALTHY"
    session.post.assert_not_called()

    # 2. Check fails (HEALTHY -> FAILING) -> sends HTML alert with tailored error
    failure_msg = "🔴 [Ingestion Pipeline Failed] 0 readings recorded in TimescaleDB"
    res2 = notifier.report_check("ingestion", healthy=False, failure_message=failure_msg)
    assert res2 is True
    assert notifier.states["ingestion"] == "FAILING"
    assert session.post.call_count == 1

    args, kwargs = session.post.call_args
    body = kwargs["json"]
    assert body["chat_id"] == 12345
    assert "<b>🚨 IotCloud Health Alert</b>" in body["text"]
    assert failure_msg in body["text"]
    assert "<i>Service: IotCloud-Health-Check</i>" in body["text"]
    assert body["parse_mode"] == "HTML"
    assert body["disable_web_page_preview"] is True

    # 3. Check fails again (FAILING -> FAILING) -> alert suppressed
    res3 = notifier.report_check("ingestion", healthy=False, failure_message=failure_msg)
    assert res3 is False
    assert session.post.call_count == 1  # Still 1 call, not repeated

    # 4. Check recovers (FAILING -> HEALTHY) -> sends recovery alert
    res4 = notifier.report_check("ingestion", healthy=True)
    assert res4 is True
    assert notifier.states["ingestion"] == "HEALTHY"
    assert session.post.call_count == 2

    _, kwargs_rec = session.post.call_args
    rec_body = kwargs_rec["json"]
    assert rec_body["text"] == "🟢 [Resolved] ingestion has recovered. All metrics are normal."
    assert rec_body["parse_mode"] == "HTML"

    # 5. Check stays healthy (HEALTHY -> HEALTHY) -> alert suppressed
    res5 = notifier.report_check("ingestion", healthy=True)
    assert res5 is False
    assert session.post.call_count == 2


def test_telegram_notifier_escapes_html_in_failure_message():
    session = MagicMock(spec=requests.Session)
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    session.post.return_value = mock_response

    notifier = TelegramNotifier(token="test-token", chat_id=12345, session=session)

    raw_error = (
        "🔴 [Public API Down] Failed to connect: "
        "ConnectTimeoutError(<HTTPSConnection(host='api.dev.iotcloud.es', port=443) at 0x7ba6>, "
        "'Connection timed out & aborted')"
    )
    res = notifier.report_check("public_api", healthy=False, failure_message=raw_error)

    assert res is True
    _, kwargs = session.post.call_args
    sent_text = kwargs["json"]["text"]
    assert "<HTTPSConnection" not in sent_text
    assert "&lt;HTTPSConnection(host='api.dev.iotcloud.es', port=443) at 0x7ba6&gt;" in sent_text
    assert "&amp; aborted" in sent_text
    assert "<b>🚨 IotCloud Health Alert</b>" in sent_text


def test_telegram_notifier_does_not_send_orphan_resolved_when_failure_alert_fails():
    session = MagicMock(spec=requests.Session)
    notifier = TelegramNotifier(token="test-token", chat_id=12345, session=session)

    # 1. Initial check is healthy
    assert notifier.report_check("public_api", healthy=True) is False
    assert notifier.states["public_api"] == "HEALTHY"

    # 2. Check fails, but Telegram API call fails (e.g. network error or 400)
    session.post.side_effect = requests.RequestException("Telegram unreachable")
    assert notifier.report_check("public_api", healthy=False, failure_message="API Down") is False
    # State must remain HEALTHY since the failure alert was never delivered
    assert notifier.states["public_api"] == "HEALTHY"

    # 3. Next cycle check recovers -> must NOT send an orphan [Resolved] message
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    session.post.side_effect = None
    session.post.return_value = mock_response

    assert notifier.report_check("public_api", healthy=True) is False
    assert session.post.call_count == 1  # Only the failed attempt from step 2


def test_telegram_notifier_retries_alerts_after_failed_delivery():
    session = MagicMock(spec=requests.Session)
    notifier = TelegramNotifier(token="test-token", chat_id=12345, session=session)

    # 1. Check fails and delivery fails -> state not updated to FAILING
    session.post.side_effect = requests.RequestException("Connection reset")
    assert notifier.report_check("api", healthy=False, failure_message="Auth0 Down") is False
    assert notifier.states.get("api") != "FAILING"

    # 2. Next cycle still failing and Telegram succeeds -> failure alert is retried and sent
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    session.post.side_effect = None
    session.post.return_value = mock_response

    assert notifier.report_check("api", healthy=False, failure_message="Auth0 Down") is True
    assert notifier.states["api"] == "FAILING"

    # 3. Check recovers, but delivery of [Resolved] fails -> state stays FAILING
    session.post.side_effect = requests.RequestException("Connection reset")
    assert notifier.report_check("api", healthy=True) is False
    assert notifier.states["api"] == "FAILING"

    # 4. Next cycle still healthy and Telegram succeeds -> [Resolved] alert is retried and sent
    session.post.side_effect = None
    session.post.return_value = mock_response
    assert notifier.report_check("api", healthy=True) is True
    assert notifier.states["api"] == "HEALTHY"
