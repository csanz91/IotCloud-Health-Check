"""Test configuration and fixtures."""

import pytest


# Ensure required environment variables are set for tests
@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_URL", "http://localhost:8001")
    monkeypatch.setenv("M2M_TOKEN", "mock-m2m-token")
    monkeypatch.setenv("AUTH0_DOMAIN", "https://iotauth.eu.auth0.com")
    monkeypatch.setenv("IOTCLOUD_LOCATION_ID", "5d0000000000000000000001")
    monkeypatch.setenv("IOTCLOUD_DEVICE_ID", "demo_virtual_hub_01")
    monkeypatch.setenv("THERMOSTAT_SENSOR_ID", "demo_thermostat")
    monkeypatch.setenv("SWITCH_SENSOR_ID", "demo_switch")
    monkeypatch.setenv("TELEGRAM_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456789")
