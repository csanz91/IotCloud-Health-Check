"""Main service entrypoint for IotCloud Health Check."""

import logging
import os
import signal
import time
from logging.handlers import RotatingFileHandler
from threading import Event

from iotcloud_health.checks.api import check_api
from iotcloud_health.checks.data_storage import check_ingestion
from iotcloud_health.checks.modules import check_thermostat
from iotcloud_health.config import settings


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

    # Console stdout handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    root_logger.addHandler(console_handler)

    # Rotating file handler
    if settings.log_path:
        log_dir = os.path.dirname(os.path.abspath(settings.log_path))
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.log_path,
            mode="a",
            maxBytes=10 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        root_logger.addHandler(file_handler)


def main() -> None:
    """Main execution loop running periodic health checks."""
    setup_logging()
    logger = logging.getLogger("iotcloud_health.main")
    logger.info("Starting IotCloud Health Check Service (Python 3.14)...")
    logger.info("Running in headless M2M API mode via Wireguard connection.")

    exit_event = Event()

    def exit_gracefully(signum: int, frame: object) -> None:
        logger.info("Shutdown signal (%s) received. Stopping gracefully...", signum)
        exit_event.set()

    signal.signal(signal.SIGINT, exit_gracefully)
    signal.signal(signal.SIGTERM, exit_gracefully)

    # Initialize last_check_time to ensure checks run immediately on startup
    last_check_time = -float(settings.check_interval_seconds)

    try:
        while not exit_event.is_set():
            now = time.monotonic()

            # Periodic full service check cycle
            if now - last_check_time >= settings.check_interval_seconds:
                last_check_time = now
                logger.info("Executing scheduled health checks...")

                # 1. Check Auth0 OIDC Infrastructure Probe & Internal API connectivity
                check_api()

                # 2. Check Ingestion Pipeline & TimescaleDB Persistence
                check_ingestion()

                # 3. Check Thermostat Discovery and Redis Actuation Roundtrip
                check_thermostat()

            # Responsive wait: sleep up to 1 second, waking immediately if shutdown signal arrives
            exit_event.wait(timeout=1.0)
    finally:
        logger.info("IotCloud Health Check Service exited cleanly.")


if __name__ == "__main__":
    main()
