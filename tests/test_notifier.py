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
