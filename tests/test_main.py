"""Tests for service wiring (logging redaction, cycle runner)."""

from __future__ import annotations

import logging

from iotcloud_health import main as main_module
from iotcloud_health.main import SecretRedactingFilter


def test_redacting_filter_masks_secrets_in_message_args_and_tracebacks():
    secret = "123456:ABC-SECRET"
    filt = SecretRedactingFilter([secret, ""])
    try:
        raise RuntimeError(f"failed POST /bot{secret}/sendMessage")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "urllib3.connectionpool",
            logging.WARNING,
            __file__,
            1,
            "Retrying %s after error: %s",
            ("Retry(total=2)", f"/bot{secret}/sendMessage"),
            sys.exc_info(),
        )
    assert filt.filter(record) is True
    formatted = logging.Formatter("%(message)s").format(record)
    assert secret not in formatted
    assert "<redacted>" in formatted


def test_run_cycle_reports_failing_checks(monkeypatch, caplog):
    monkeypatch.setattr(
        main_module,
        "CHECKS",
        (("ok", lambda: {"fine": True}), ("broken", lambda: None)),
    )
    logger = logging.getLogger("test.main")
    with caplog.at_level(logging.INFO):
        main_module.run_cycle(logger)
    assert "1/2 failing (broken)" in caplog.text
