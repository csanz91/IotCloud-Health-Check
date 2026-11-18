"""Main service entrypoint for IotCloud Health Check."""

import logging
import os
import signal
import time
from logging.handlers import RotatingFileHandler
from threading import Event

from iotcloud_health import __version__
from iotcloud_health.checks.api import check_api
from iotcloud_health.checks.data_storage import check_ingestion
from iotcloud_health.checks.devices import check_devices
from iotcloud_health.checks.modules import check_thermostat
from iotcloud_health.checks.mqtt import check_mqtt_wss
from iotcloud_health.checks.mqtt_device import check_mqtt_device_login
from iotcloud_health.checks.ota import check_ota
from iotcloud_health.checks.public_api import check_public_api
from iotcloud_health.config import settings
from iotcloud_health.notifier import default_notifier


class SecretRedactingFilter(logging.Filter):
    """Masks configured secrets in every log record (e.g. the Telegram bot token that
    urllib3 includes in retry warnings for /bot<TOKEN>/sendMessage)."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s and len(s) >= 6]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        message = record.getMessage()
        redacted = message
        for secret in self._secrets:
            redacted = redacted.replace(secret, "<redacted>")
        if redacted != message:
            record.msg = redacted
            record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            for secret in self._secrets:
                record.exc_text = record.exc_text.replace(secret, "<redacted>")
        return True


def setup_logging() -> None:
    """Configures structured dual logging to console and rotating log file."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s <%(levelname).1s> %(name)s:%(funcName)s:%(lineno)s: %(message)s"
    )
    redactor = SecretRedactingFilter([settings.telegram_token, settings.m2m_token])

    # Console stdout handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    console_handler.addFilter(redactor)
    root_logger.addHandler(console_handler)

    # Rotating file handler
    if settings.log_path:
        try:
            log_dir = os.path.dirname(os.path.abspath(settings.log_path))
            os.makedirs(log_dir, exist_ok=True)
            file_handler = RotatingFileHandler(
                settings.log_path,
                mode="a",
                maxBytes=10 * 1024 * 1024,
                backupCount=2,
                encoding="utf-8",
            )
        except OSError as err:
            # e.g. a bind-mounted log dir not writable by the container user:
            # keep running with console logging rather than crash-looping.
            logging.getLogger("iotcloud_health.main").warning(
                "Cannot write log file %s (%s); logging to console only.", settings.log_path, err
            )
        else:
            file_handler.setFormatter(formatter)
            file_handler.setLevel(log_level)
            file_handler.addFilter(redactor)
            root_logger.addHandler(file_handler)


CHECKS = (
    ("public_api", check_public_api),  # Public API reachability & SSL validity
    ("mqtt_wss", check_mqtt_wss),  # MQTT broker over WSS & WebSocket upgrade
    ("mqtt_device", check_mqtt_device_login),  # Device login on 1883 via EMQX authn/authz
    ("ota", check_ota),  # OTA firmware server reachable through nginx
    ("api", check_api),  # Auth0 OIDC/JWKS & Internal API connectivity
    ("ingestion", check_ingestion),  # Ingestion pipeline & TimescaleDB freshness
    ("thermostat", check_thermostat),  # Thermostat discovery & actuation roundtrip
    ("devices", check_devices),  # Watched real devices online
)


def warn_on_missing_config(logger: logging.Logger) -> None:
    """Logs loud warnings for settings that make the service silently useless."""
    if not settings.m2m_token:
        logger.error("M2M_TOKEN is not set: internal API checks will fail with 401/403.")
    if not settings.telegram_token or not settings.telegram_chat_id:
        logger.error(
            "TELEGRAM_TOKEN / TELEGRAM_CHAT_ID are not set: failures will only be logged, "
            "no alerts will be delivered."
        )


def run_cycle(logger: logging.Logger) -> None:
    """Runs every health check once and logs a one-line summary."""
    logger.info("Executing scheduled health checks...")
    started = time.monotonic()
    # Batch so that an outage tripping several checks sends one Telegram message.
    with default_notifier.batch():
        failed = [name for name, check in CHECKS if check() is None]
    elapsed = time.monotonic() - started
    if failed:
        logger.warning(
            "Health check cycle finished in %.1fs: %d/%d failing (%s)",
            elapsed,
            len(failed),
            len(CHECKS),
            ", ".join(failed),
        )
    else:
        logger.info("Health check cycle finished in %.1fs: all %d healthy", elapsed, len(CHECKS))


def main() -> None:
    """Main execution loop running periodic health checks."""
    setup_logging()
    logger = logging.getLogger("iotcloud_health.main")
    logger.info("Starting IotCloud Health Check Service v%s...", __version__)
    logger.info(
        "Interval: %ss, alert after %d consecutive failure(s)",
        settings.check_interval_seconds,
        settings.alert_after_failures,
    )
    warn_on_missing_config(logger)

    exit_event = Event()

    def exit_gracefully(signum: int, frame: object) -> None:
        logger.info("Shutdown signal (%s) received. Stopping gracefully...", signum)
        exit_event.set()

    signal.signal(signal.SIGINT, exit_gracefully)
    signal.signal(signal.SIGTERM, exit_gracefully)

    try:
        while not exit_event.is_set():
            cycle_start = time.monotonic()
            run_cycle(logger)
            # Sleep until the next cycle, waking immediately on shutdown signals.
            remaining = settings.check_interval_seconds - (time.monotonic() - cycle_start)
            exit_event.wait(timeout=max(remaining, 1.0))
    finally:
        logger.info("IotCloud Health Check Service exited cleanly.")


if __name__ == "__main__":
    main()
