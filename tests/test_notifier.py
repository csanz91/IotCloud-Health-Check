"""Tests for Telegram notification dispatching."""

from unittest.mock import MagicMock

import requests

from iotcloud_health.notifier import TelegramNotifier


def test_telegram_notifier_success():
    session = MagicMock(spec=requests.Session)
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    session.post.return_value = mock_response

    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )
    result = notifier.send_message("Service is working")

    assert result is True
    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert "https://api.telegram.org/bottest-token/sendMessage" in args[0]
    assert kwargs["json"]["chat_id"] == 12345
    assert kwargs["json"]["text"] == "Service is working"
    assert kwargs["json"]["parse_mode"] == "HTML"


def test_telegram_notifier_failure():
    session = MagicMock(spec=requests.Session)
    session.post.side_effect = requests.RequestException("Network error")

    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )
    result = notifier.send_message("Service failed")

    assert result is False


def test_telegram_notifier_state_transitions():
    session = MagicMock(spec=requests.Session)
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    session.post.return_value = mock_response

    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )

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
    assert body["text"].startswith("🚨 <b>Ingestion Pipeline Failed</b>\nTelemetry ingestion")
    assert "0 readings recorded in TimescaleDB" in body["text"]
    assert "🔴" not in body["text"]
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
    assert rec_body["text"].startswith("✅ <b>Telemetry ingestion recovered</b>\nDown for ")
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

    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )

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
    assert sent_text.startswith("🚨 <b>Public API Down</b>")


def test_telegram_notifier_does_not_send_orphan_resolved_when_failure_alert_fails():
    session = MagicMock(spec=requests.Session)
    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )

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
    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )

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


def _ok_session() -> MagicMock:
    session = MagicMock(spec=requests.Session)
    ok = MagicMock()
    ok.raise_for_status.return_value = None
    session.post.return_value = ok
    return session


def test_failure_threshold_defers_alert_until_consecutive_failures():
    session = _ok_session()
    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=3
    )

    assert notifier.report_check("mqtt_wss", healthy=False, failure_message="down") is False
    assert notifier.report_check("mqtt_wss", healthy=False, failure_message="down") is False
    session.post.assert_not_called()

    assert notifier.report_check("mqtt_wss", healthy=False, failure_message="down") is True
    assert session.post.call_count == 1
    assert notifier.states["mqtt_wss"] == "FAILING"


def test_transient_failure_below_threshold_never_alerts():
    session = _ok_session()
    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=2
    )

    assert notifier.report_check("api", healthy=False, failure_message="blip") is False
    assert notifier.report_check("api", healthy=True) is False  # no orphan [Resolved]
    assert notifier.report_check("api", healthy=False, failure_message="blip") is False
    session.post.assert_not_called()  # counter was reset by the healthy run


def test_recovery_message_includes_downtime():
    from datetime import UTC, datetime, timedelta

    session = _ok_session()
    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    notifier.report_check("api", healthy=False, failure_message="x", timestamp=t0)
    notifier.report_check("api", healthy=True, timestamp=t0 + timedelta(hours=1, minutes=5))

    text = session.post.call_args.kwargs["json"]["text"]
    assert text.startswith("✅ <b>Auth0 &amp; Internal API recovered</b>")
    assert "Down for 1h 5m (since 13:00 CET)" in text


def test_oversized_failure_message_is_capped_below_telegram_limit():
    session = _ok_session()
    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )

    huge = "<html>" + "&" * 20_000 + "</html>"
    assert notifier.report_check("api", healthy=False, failure_message=huge) is True
    text = session.post.call_args.kwargs["json"]["text"]
    assert len(text) < 4096
    assert "[truncated]" in text
    assert "<html>" not in text


def test_bot_token_is_not_logged_on_delivery_failure(caplog):
    session = MagicMock(spec=requests.Session)
    token = "999999:SECRET-BOT-TOKEN"
    session.post.side_effect = requests.ConnectionError(
        f"HTTPSConnectionPool(host='api.telegram.org'): Max retries exceeded with url: "
        f"/bot{token}/sendMessage"
    )
    notifier = TelegramNotifier(token=token, chat_id=12345, session=session)

    with caplog.at_level("DEBUG"):
        assert notifier.send_message("hello") is False

    assert token not in caplog.text
    assert "<redacted>" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_batch_combines_simultaneous_failures_into_one_message():
    session = _ok_session()
    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )
    with notifier.batch():
        notifier.report_check("api", healthy=False, failure_message="🔴 [Internal API Down] x")
        notifier.report_check("ingestion", healthy=False, failure_message="🔴 [Database Error] y")
        notifier.report_check("ota", healthy=True)
        session.post.assert_not_called()

    assert session.post.call_count == 1
    text = session.post.call_args.kwargs["json"]["text"]
    assert text.startswith("🚨 <b>2 checks failing</b>")
    assert "<b>Auth0 &amp; Internal API</b> · Internal API Down\nx" in text
    assert "<b>Telemetry ingestion</b> · Database Error\ny" in text
    assert notifier.states["api"] == notifier.states["ingestion"] == "FAILING"


def test_batch_sends_failures_and_recoveries_separately_with_still_failing_footer():
    session = _ok_session()
    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )
    with notifier.batch():
        for name in ("api", "ingestion", "ota"):
            notifier.report_check(name, healthy=False, failure_message="🔴 [Down] z")
    session.post.reset_mock()

    with notifier.batch():
        notifier.report_check("api", healthy=True)
        notifier.report_check("ingestion", healthy=True)
        notifier.report_check("ota", healthy=False, failure_message="🔴 [Down] z")

    assert session.post.call_count == 1
    text = session.post.call_args.kwargs["json"]["text"]
    assert text.startswith("✅ <b>2 checks recovered</b>")
    assert "• Auth0 &amp; Internal API: down" in text
    assert text.endswith("⚠️ Still failing: OTA firmware server")


def test_undelivered_batch_is_retried_next_cycle():
    session = MagicMock(spec=requests.Session)
    session.post.side_effect = requests.ConnectionError("telegram down")
    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )
    with notifier.batch():
        notifier.report_check("api", healthy=False, failure_message="🔴 [Down] z")
    assert notifier.states.get("api") != "FAILING"

    session.post.side_effect = None
    session.post.return_value = MagicMock()
    with notifier.batch():
        notifier.report_check("api", healthy=False, failure_message="🔴 [Down] z")
    assert notifier.states["api"] == "FAILING"


def test_display_name_is_used_in_recovery_message():
    session = _ok_session()
    notifier = TelegramNotifier(
        token="test-token", chat_id=12345, session=session, failure_threshold=1
    )
    notifier.report_check(
        "device:abc",
        healthy=False,
        failure_message="🔴 [Device Offline] Habitaciones (abc)",
        display_name="Habitaciones",
    )
    notifier.report_check("device:abc", healthy=True)
    text = session.post.call_args.kwargs["json"]["text"]
    assert text.startswith("✅ <b>Habitaciones recovered</b>")


def test_untagged_message_uses_label_as_title_and_unknown_timezone_falls_back_to_utc():
    session = _ok_session()
    notifier = TelegramNotifier(
        token="test-token",
        chat_id=12345,
        session=session,
        failure_threshold=1,
        timezone="Not/AZone",
    )
    notifier.report_check("thermostat", healthy=False, failure_message="plain error")
    text = session.post.call_args.kwargs["json"]["text"]
    assert text.startswith("🚨 <b>Thermostat roundtrip failing</b>")
    assert " UTC" in text
