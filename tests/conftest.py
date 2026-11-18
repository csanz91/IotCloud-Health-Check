"""Test configuration and fixtures.

`iotcloud_health.config.settings` is built at import time, before any fixture runs,
and would otherwise read the developer's real `.env` (including the live Telegram
bot token). Environment variables take precedence over `.env`, so pin every
setting here at conftest import time, which happens before test modules import
the package.
"""

import os

import pytest

TEST_ENV = {
    "INTERNAL_API_URL": "http://localhost:8001",
    "M2M_TOKEN": "mock-m2m-token",
    "AUTH0_DOMAIN": "https://iotauth.eu.auth0.com",
    "IOTCLOUD_LOCATION_ID": "5d0000000000000000000001",
    "IOTCLOUD_DEVICE_ID": "demo_virtual_hub_01",
    "THERMOSTAT_SENSOR_ID": "demo_thermostat",
    "SWITCH_SENSOR_ID": "demo_switch",
    # Fake credentials: a test that reaches the default notifier can never message a real chat.
    "TELEGRAM_TOKEN": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
    "TELEGRAM_CHAT_ID": "123456789",
    "PUBLIC_API_URL": "https://api.example.test/api/v2/health",
    "MQTT_WSS_URL": "wss://mqtt.example.test/mqtt",
    "MQTT_TCP_HOST": "mqtt.example.test",
    "MQTT_TCP_PORT": "1883",
    "OTA_URL": "https://ota.example.test/",
    "WATCHED_SENSOR_IDS": "",
    "SSL_MIN_DAYS_VALID": "7",
    "ALERT_AFTER_FAILURES": "2",
    "CHECK_INTERVAL_SECONDS": "300",
    "LOG_PATH": "",
    "LOG_LEVEL": "INFO",
}
os.environ.update(TEST_ENV)


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
