"""Service check decorator and health state tracking."""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from iotcloud_health.notifier import default_notifier, report_check, send_notification

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("iotcloud_health.checker")

P = ParamSpec("P")
R = TypeVar("R")


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


def check_service(
    service_name: str,
    notifier: Any = default_notifier,
) -> Callable[[Callable[P, R]], Callable[P, R | None]]:
    """Decorates a health check function to monitor its health and send state-change alerts."""

    def decorator(func: Callable[P, R]) -> Callable[P, R | None]:
        failure_reported = False

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
            nonlocal failure_reported
            try:
                result = func(*args, **kwargs)
                if hasattr(notifier, "report_check"):
                    notifier.report_check(service_name, healthy=True)
                elif notifier is send_notification:
                    report_check(service_name, healthy=True)
                elif failure_reported:
                    logger.info("%s is now working again", service_name)
                    notifier(f"{service_name} is now working \u2705")
                    failure_reported = False
                return result
            except Exception as exc:
                logger.exception("Health check failed for service: %s", service_name)
                failure_msg = (
                    exc.message
                    if isinstance(exc, HealthCheckError)
                    else f"{service_name} is not working \u274c"
                )

                if hasattr(notifier, "report_check"):
                    notifier.report_check(service_name, healthy=False, failure_message=failure_msg)
                elif notifier is send_notification:
                    report_check(service_name, healthy=False, failure_message=failure_msg)
                elif not failure_reported:
                    notifier(failure_msg)
                    failure_reported = True
                return None

        return wrapper

    return decorator

