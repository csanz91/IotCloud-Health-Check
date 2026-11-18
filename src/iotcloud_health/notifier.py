"""Telegram notification dispatcher with state-transition filtering.

Check outcomes are reported with `report_check`. Only transitions are announced
(HEALTHY -> FAILING after `failure_threshold` consecutive failures, and back).
Inside `with notifier.batch():` transitions are collected and sent as one
combined message per kind when the block ends, so an outage that trips several
checks at once produces one alert instead of a burst.
"""

from __future__ import annotations

import html
import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from iotcloud_health.config import settings

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("iotcloud_health.notifier")

# Telegram rejects messages longer than 4096 characters (after entity parsing).
# Budget for the message bodies; the surrounding template stays well below the rest.
MAX_FAILURE_MESSAGE_CHARS = 3500

# Human names for the check keys used by the checks.
CHECK_LABELS = {
    "public_api": "Public API",
    "mqtt_wss": "MQTT for the app (WSS)",
    "mqtt_device": "MQTT device login (1883)",
    "ota": "OTA firmware server",
    "api": "Auth0 & Internal API",
    "ingestion": "Telemetry ingestion",
    "thermostat": "Thermostat roundtrip",
    "devices": "Device status query",
}

# Check failure messages look like "🔴 [Title] body"; the title becomes the headline.
_TAGGED_MESSAGE = re.compile(r"^\s*🔴\s*\[(?P<title>[^\]]+)\]\s*(?P<body>.*)$", re.DOTALL)


def _create_default_session() -> requests.Session:
    """Creates a requests.Session with retry logic for transient network/keep-alive errors."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _escape_and_cap(text: str, limit: int = MAX_FAILURE_MESSAGE_CHARS) -> str:
    """HTML-escapes text, truncating the raw input so the escaped result fits in `limit`."""
    escaped = _esc(text)
    if len(escaped) <= limit:
        return escaped
    cut = limit
    while cut > 0:
        escaped = _esc(text[:cut]) + "… [truncated]"
        if len(escaped) <= limit:
            return escaped
        cut = int(cut * 0.8)
    return "… [truncated]"


def _format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return f"{int(seconds)}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 1:
        return f"{minutes}m"
    days, hours = divmod(hours, 24)
    if days < 1:
        return f"{hours}h {minutes}m"
    return f"{days}d {hours}h"


def _split_message(message: str) -> tuple[str | None, str]:
    match = _TAGGED_MESSAGE.match(message)
    if match:
        return match.group("title").strip(), match.group("body").strip()
    return None, message.strip()


def _load_timezone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        logger.warning("Unknown ALERT_TIMEZONE %r; showing times in UTC", name)
        return UTC


@dataclass
class _Transition:
    check_name: str
    failing: bool
    message: str
    since: datetime
    at: datetime


class TelegramNotifier:
    """Dispatches HTML notifications to a Telegram chat with state-transition guards.

    A check must fail `failure_threshold` consecutive times before a failure alert is
    sent, which suppresses alerts caused by one-off network blips. A state change is
    only recorded once its message was delivered, so undelivered alerts are retried
    on the next report.
    """

    def __init__(
        self,
        token: str | None = None,
        chat_id: int | None = None,
        session: requests.Session | None = None,
        failure_threshold: int | None = None,
        timezone: str | None = None,
    ) -> None:
        self.token = token or settings.telegram_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self.failure_threshold = max(1, failure_threshold or settings.alert_after_failures)
        self.tz = _load_timezone(timezone or settings.alert_timezone)
        self._session = session or _create_default_session()
        # check_name -> "HEALTHY" | "FAILING" (last state successfully announced)
        self.states: dict[str, str] = {}
        # check_name -> number of consecutive failed runs
        self.failure_counts: dict[str, int] = {}
        # check_name -> time of the first failure in the current streak
        self.failing_since: dict[str, datetime] = {}
        # check_name -> display name (e.g. a device's name), overrides CHECK_LABELS
        self.labels: dict[str, str] = {}
        self._pending: dict[str, _Transition] = {}
        self._batching = False

    # ------------------------------------------------------------------ sending

    def _redact(self, text: str) -> str:
        return text.replace(self.token, "<redacted>") if self.token else text

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Sends a message to Telegram. Returns True on success."""
        if not self.token or not self.chat_id:
            logger.warning("Telegram token or chat_id not configured. Message suppressed: %s", text)
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            response = self._session.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:
            # Never use logger.exception here: the traceback and the exception text
            # contain the request URL, which embeds the bot token.
            resp_body = getattr(exc.response, "text", None) or ""
            logger.error(
                "Failed to send Telegram notification: %s %s | message: %s",
                type(exc).__name__,
                self._redact(f"{exc} {resp_body}".strip()),
                text,
            )
            return False
        logger.info("Telegram notification sent: %s", text)
        return True

    # ------------------------------------------------------------- state machine

    def label(self, check_name: str) -> str:
        return self.labels.get(check_name) or CHECK_LABELS.get(check_name) or check_name

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Collects transitions reported inside the block and sends them together."""
        self._batching = True
        try:
            yield
        finally:
            self._batching = False
            self.flush()

    def report_check(
        self,
        check_name: str,
        healthy: bool,
        failure_message: str = "",
        timestamp: datetime | None = None,
        *,
        display_name: str | None = None,
    ) -> bool:
        """Records a check outcome and notifies on state transitions (HEALTHY <-> FAILING).

        Returns True if a notification was dispatched (always False while batching;
        the batch sends on exit).
        """
        if display_name:
            self.labels[check_name] = display_name
        now = timestamp or datetime.now(UTC)
        previous_state = self.states.get(check_name, "HEALTHY")
        self._pending.pop(check_name, None)

        if healthy:
            self.failure_counts.pop(check_name, None)
            if previous_state != "FAILING":
                # Healthy, or recovered before the alert threshold was reached.
                self.failing_since.pop(check_name, None)
                self.states[check_name] = "HEALTHY"
                return False
            since = self.failing_since.get(check_name, now)
            self._pending[check_name] = _Transition(check_name, False, "", since, now)
        else:
            count = self.failure_counts.get(check_name, 0) + 1
            self.failure_counts[check_name] = count
            since = self.failing_since.setdefault(check_name, now)
            if previous_state == "FAILING":
                return False  # Already alerted; do not repeat.
            if count < self.failure_threshold:
                logger.warning(
                    "Check '%s' failed (%d/%d consecutive); alert deferred",
                    check_name,
                    count,
                    self.failure_threshold,
                )
                return False
            self._pending[check_name] = _Transition(check_name, True, failure_message, since, now)

        return False if self._batching else self.flush()

    def flush(self) -> bool:
        """Sends pending transitions: one message for new failures, one for recoveries."""
        pending = list(self._pending.values())
        self._pending.clear()
        failures = [t for t in pending if t.failing]
        recoveries = [t for t in pending if not t.failing]

        sent_any = False
        if failures and self.send_message(self._render_failures(failures)):
            for t in failures:
                self.states[t.check_name] = "FAILING"
            sent_any = True
        if recoveries and self.send_message(self._render_recoveries(recoveries)):
            for t in recoveries:
                self.states[t.check_name] = "HEALTHY"
                self.failing_since.pop(t.check_name, None)
            sent_any = True
        return sent_any

    # ---------------------------------------------------------------- rendering

    def _fmt_time(self, ts: datetime, now: datetime) -> str:
        local = ts.astimezone(self.tz)
        if local.date() == now.astimezone(self.tz).date():
            return local.strftime("%H:%M %Z")
        return local.strftime("%d %b %H:%M %Z")

    def _still_failing_footer(self, exclude: set[str]) -> str:
        names = sorted(
            self.label(name)
            for name, state in self.states.items()
            if state == "FAILING" and name not in exclude
        )
        if not names:
            return ""
        return f"\n\n⚠️ Still failing: {_esc(', '.join(names))}"

    def _render_failures(self, failures: list[_Transition]) -> str:
        now = max(t.at for t in failures)
        names = {t.check_name for t in failures}
        footer = self._still_failing_footer(names)

        if len(failures) == 1:
            t = failures[0]
            title, body = _split_message(t.message)
            label = self.label(t.check_name)
            return (
                f"🚨 <b>{_esc(title or f'{label} failing')}</b>\n"
                f"{_esc(label)} · failing since {self._fmt_time(t.since, now)}\n\n"
                f"{_escape_and_cap(body)}"
                f"{footer}"
            )

        per_item = MAX_FAILURE_MESSAGE_CHARS // len(failures)
        sections = []
        for t in sorted(failures, key=lambda t: t.since):
            title, body = _split_message(t.message)
            heading = f"<b>{_esc(self.label(t.check_name))}</b>"
            if title:
                heading += f" · {_esc(title)}"
            sections.append(f"{heading}\n{_escape_and_cap(body, per_item)}")
        since = min(t.since for t in failures)
        return (
            f"🚨 <b>{len(failures)} checks failing</b>\n"
            f"since {self._fmt_time(since, now)}\n\n" + "\n\n".join(sections) + footer
        )

    def _render_recoveries(self, recoveries: list[_Transition]) -> str:
        now = max(t.at for t in recoveries)
        footer = self._still_failing_footer({t.check_name for t in recoveries})

        if len(recoveries) == 1:
            t = recoveries[0]
            return (
                f"✅ <b>{_esc(self.label(t.check_name))} recovered</b>\n"
                f"Down for {_format_duration((t.at - t.since).total_seconds())} "
                f"(since {self._fmt_time(t.since, now)})"
                f"{footer}"
            )

        lines = [
            f"• {_esc(self.label(t.check_name))}: down "
            f"{_format_duration((t.at - t.since).total_seconds())}"
            for t in sorted(recoveries, key=lambda t: t.since)
        ]
        return f"✅ <b>{len(recoveries)} checks recovered</b>\n" + "\n".join(lines) + footer


# Default module-level notifier
default_notifier = TelegramNotifier()
