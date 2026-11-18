"""Tests for the check_service decorator."""

from __future__ import annotations

from unittest.mock import MagicMock

import requests

from iotcloud_health.checker import HealthCheckError, check_service, response_detail


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


def test_checker_success_reports_healthy_and_preserves_metadata():
    reporter = RecordingReporter()

    @check_service("TestService", notifier=reporter)
    def my_check():
        """Sample docstring."""
        return "ok"

    assert my_check.__name__ == "my_check"
    assert my_check.__doc__ == "Sample docstring."
    assert my_check() == "ok"
    assert reporter.calls == [("TestService", True, "")]


def test_checker_unexpected_exception_reports_generic_failure():
    reporter = RecordingReporter()

    @check_service("MockService", notifier=reporter)
    def sample_check():
        raise ValueError("Something broke")

    assert sample_check() is None
    [(name, healthy, msg)] = reporter.calls
    assert name == "MockService"
    assert healthy is False
    assert "MockService" in msg
    assert "ValueError: Something broke" in msg


def test_checker_with_health_check_error_uses_tailored_message():
    reporter = RecordingReporter()

    @check_service("ingestion", notifier=reporter)
    def failing_check():
        raise HealthCheckError("🔴 [M2M Auth Failed] Internal API rejected X-M2M-Token.")

    assert failing_check() is None
    assert reporter.calls == [
        ("ingestion", False, "🔴 [M2M Auth Failed] Internal API rejected X-M2M-Token.")
    ]


def test_response_detail_collapses_whitespace_and_truncates():
    resp = MagicMock(spec=requests.Response)
    resp.text = "line1\n\n   line2\t" + "y" * 1000
    detail = response_detail(resp, limit=50)
    assert "\n" not in detail
    assert detail.startswith("line1 line2 ")
    assert detail.endswith("… [truncated]")
    assert len(detail) < 70
