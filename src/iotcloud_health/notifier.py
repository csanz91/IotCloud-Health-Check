"""Telegram notification dispatcher with state-transition filtering."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import requests

from iotcloud_health.config import settings

logger = logging.getLogger("iotcloud_health.notifier")


class TelegramNotifier:
    """Dispatches HTML/Markdown notifications to a Telegram chat with state-transition guards."""

    def __init__(
        self,
        token: str | None = None,
        chat_id: int | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.token = token or settings.telegram_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self._session = session or requests.Session()
        # check_name -> "HEALTHY" | "FAILING"
        self.states: dict[str, str] = {}

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Sends a message to Telegram."""
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
            logger.info("Telegram notification sent: %s", text)
            return True
        except requests.RequestException:
            logger.exception("Failed to send Telegram notification: %s", text)
            return False

    def report_check(
        self,
        check_name: str,
        healthy: bool,
        failure_message: str = "",
        timestamp: datetime | None = None,
    ) -> bool:
        """Guards and notifies on state transitions (HEALTHY <-> FAILING).

        Returns True if a notification was dispatched, False otherwise.
        """
        previous_state = self.states.get(check_name, "HEALTHY")
        current_state = "HEALTHY" if healthy else "FAILING"

        if previous_state == current_state and check_name in self.states:
            # State did not change; do not repeat alerts
            return False

        self.states[check_name] = current_state

        if current_state == "FAILING":
            # State transitioned to FAILING -> send failure alert
            ts = timestamp or datetime.now(UTC)
            utc_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC")
            text = (
                "<b>🚨 IotCloud Health Alert</b>\n\n"
                f"{failure_message}\n\n"
                "<i>Service: IotCloud-Health-Check</i>\n"
                f"<i>Time: {utc_str}</i>"
            )
            return self.send_message(text, parse_mode="HTML")

        if current_state == "HEALTHY" and previous_state == "FAILING":
            # State transitioned from FAILING to HEALTHY -> send recovery alert
            text = f"🟢 [Resolved] {check_name} has recovered. All metrics are normal."
            return self.send_message(text, parse_mode="HTML")

        # Initial check was healthy: record state, no alert needed
        return False

    def send_notification(self, message: str) -> bool:
        """Backward-compatible markdown notification dispatcher."""
        return self.send_message(f"[IotCloud]: {message}", parse_mode="markdown")


# Default module-level notifier
default_notifier = TelegramNotifier()


def send_notification(message: str) -> bool:
    return default_notifier.send_notification(message)


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    return default_notifier.send_message(text, parse_mode=parse_mode)


def report_check(
    check_name: str,
    healthy: bool,
    failure_message: str = "",
    timestamp: datetime | None = None,
) -> bool:
    return default_notifier.report_check(
        check_name,
        healthy=healthy,
        failure_message=failure_message,
        timestamp=timestamp,
    )
