"""Service check decorator, shared HTTP session and error helpers."""

from __future__ import annotations

import functools
import logging
import re
from typing import TYPE_CHECKING, ParamSpec, Protocol, TypeVar

import requests

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("iotcloud_health.checker")

P = ParamSpec("P")
R = TypeVar("R")

# Maximum characters of a remote response body embedded in an alert message.
DETAIL_MAX_CHARS = 300

_shared_session: requests.Session | None = None


def get_session() -> requests.Session:
    """Returns a process-wide HTTP session so connections are pooled across check cycles."""
    global _shared_session
    if _shared_session is None:
        _shared_session = requests.Session()
    return _shared_session


def response_detail(resp: requests.Response, limit: int = DETAIL_MAX_CHARS) -> str:
    """Returns a short, single-line excerpt of a response body for alert messages."""
    text = " ".join((resp.text or "").split())
    if len(text) > limit:
        return f"{text[:limit]}… [truncated]"
    return text


_ERRNO_RE = re.compile(r"\[Errno -?\d+\] [^'\"()\]]+")
_SSL_RE = re.compile(r"\[SSL: [A-Z_]+\][^'\"()]*")


def describe_error(err: BaseException) -> str:
    """Summarizes a network exception for humans.

    urllib3 wraps the real cause in "HTTPConnectionPool(host=..., port=...): Max retries
    exceeded with url: ... (Caused by NewConnectionError(...))"; alerts only need the cause.
    """
    if isinstance(err, requests.Timeout | TimeoutError):
        return "timed out"
    text = str(err)
    for pattern in (_SSL_RE, _ERRNO_RE):
        match = pattern.search(text)
        if match:
            return match.group(0).strip().rstrip(".:,")
    if isinstance(err, requests.ConnectionError):
        return "connection failed"
    if len(text) > 200:
        text = f"{text[:200]}…"
    return text or type(err).__name__


class HealthCheckError(Exception):
    """Exception carrying tailored failure messages for health check alerts."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail


class CheckReporter(Protocol):
    """Anything that can receive check outcomes (e.g. TelegramNotifier)."""

    def report_check(
        self,
        check_name: str,
        healthy: bool,
        failure_message: str = "",
        *,
        display_name: str | None = None,
    ) -> bool: ...


def _default_reporter() -> CheckReporter:
    from iotcloud_health.notifier import default_notifier

    return default_notifier


def check_service(
    service_name: str,
    notifier: CheckReporter | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R | None]]:
    """Decorates a health check so its outcome is reported and exceptions never escape.

    The wrapped function returns the check's result on success, or None on failure.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R | None]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
            reporter = notifier or _default_reporter()
            try:
                result = func(*args, **kwargs)
            except HealthCheckError as exc:
                logger.error("Health check '%s' failed: %s", service_name, exc.message)
                reporter.report_check(service_name, healthy=False, failure_message=exc.message)
                return None
            except Exception as exc:
                logger.exception("Health check '%s' crashed unexpectedly", service_name)
                reporter.report_check(
                    service_name,
                    healthy=False,
                    failure_message=(
                        f"🔴 [{service_name}] Check failed unexpectedly: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
                return None
            reporter.report_check(service_name, healthy=True)
            return result

        return wrapper

    return decorator
