from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from iotcloud_health.checks.ssl_helper import get_ssl_days_remaining


def test_get_ssl_days_remaining_success():
    mock_ssock = MagicMock()
    # 30 days in the future
    future_date = datetime.now(UTC).replace(microsecond=0)
    future_date = future_date.replace(year=future_date.year + 1)
    date_str = future_date.strftime("%b %d %H:%M:%S %Y GMT")
    mock_ssock.getpeercert.return_value = {"notAfter": date_str}

    with (
        patch("socket.create_connection"),
        patch("ssl.create_default_context") as mock_ctx,
    ):
        mock_ctx.return_value.wrap_socket.return_value.__enter__.return_value = mock_ssock
        days = get_ssl_days_remaining("example.com", 443)
        assert days > 300


def test_get_ssl_days_remaining_missing_cert():
    mock_ssock = MagicMock()
    mock_ssock.getpeercert.return_value = {}

    with (
        patch("socket.create_connection"),
        patch("ssl.create_default_context") as mock_ctx,
    ):
        mock_ctx.return_value.wrap_socket.return_value.__enter__.return_value = mock_ssock
        with pytest.raises(ValueError, match="No SSL certificate or notAfter"):
            get_ssl_days_remaining("example.com", 443)


def test_verify_certificate_reports_expired_cert_from_handshake_failure():
    import ssl

    import pytest

    from iotcloud_health.checker import HealthCheckError
    from iotcloud_health.checks.ssl_helper import verify_certificate

    err = ssl.SSLCertVerificationError(1, "certificate verify failed")
    err.verify_code = 10  # X509_V_ERR_CERT_HAS_EXPIRED
    err.verify_message = "certificate has expired"

    with (
        patch("iotcloud_health.checks.ssl_helper.get_ssl_days_remaining", side_effect=err),
        pytest.raises(HealthCheckError) as exc_info,
    ):
        verify_certificate("example.com", 443, label="Public", impact="X.", min_days_valid=7)
    assert "[Public SSL Expired]" in exc_info.value.message


def test_verify_certificate_reports_other_verification_failures():
    import ssl

    import pytest

    from iotcloud_health.checker import HealthCheckError
    from iotcloud_health.checks.ssl_helper import verify_certificate

    err = ssl.SSLCertVerificationError(1, "certificate verify failed")
    err.verify_code = 62  # hostname mismatch
    err.verify_message = "Hostname mismatch"

    with (
        patch("iotcloud_health.checks.ssl_helper.get_ssl_days_remaining", side_effect=err),
        pytest.raises(HealthCheckError) as exc_info,
    ):
        verify_certificate("example.com", 443, label="MQTT", impact="X.", min_days_valid=7)
    assert "[MQTT SSL Failed]" in exc_info.value.message
    assert "Hostname mismatch" in exc_info.value.message
