"""Tests for configuration settings."""

from iotcloud_health.config import Settings


def test_settings_load_from_env():
    settings = Settings(
        internal_api_url="http://wireguard-server:8001",
        m2m_token="m2m-test-token-12345",
        auth0_domain="https://auth0.example.com",
        iotcloud_location_id="loc-demo-01",
        iotcloud_device_id="hub-demo-01",
        thermostat_sensor_id="thermostat_01",
        switch_sensor_id="switch_01",
        telegram_token="custom-tel-token",
        telegram_chat_id=987654321,
    )
    assert settings.internal_api_url == "http://wireguard-server:8001"
    assert settings.m2m_token == "m2m-test-token-12345"
    assert settings.auth0_domain == "https://auth0.example.com"
    assert settings.iotcloud_location_id == "loc-demo-01"
    assert settings.iotcloud_device_id == "hub-demo-01"
    assert settings.thermostat_sensor_id == "thermostat_01"
    assert settings.switch_sensor_id == "switch_01"
    assert settings.telegram_token == "custom-tel-token"
    assert settings.telegram_chat_id == 987654321
    assert settings.check_interval_seconds == 300


def test_settings_m2m_defaults_and_aliases():
    # Verify model field defaults
    assert Settings.model_fields["internal_api_url"].default == "http://localhost:8001"
    assert Settings.model_fields["thermostat_sensor_id"].default == "demo_thermostat"
    assert Settings.model_fields["switch_sensor_id"].default == "demo_switch"
    assert Settings.model_fields["iotcloud_location_id"].default == "5d0000000000000000000001"
    assert Settings.model_fields["iotcloud_device_id"].default == "demo_virtual_hub_01"

    # Custom M2M settings via uppercase aliases
    data = {
        "INTERNAL_API_URL": "http://api-internal:8001",
        "M2M_TOKEN": "secret-m2m-token-123",
        "AUTH0_DOMAIN": "https://custom.auth0.com",
        "LOCATION_ID": "custom-loc-id",
        "DEVICE_ID": "custom-dev-id",
        "THERMOSTAT_SENSOR_ID": "thermostat_custom",
        "SWITCH_SENSOR_ID": "switch_custom",
    }
    settings_custom = Settings.model_validate(data)
    assert settings_custom.internal_api_url == "http://api-internal:8001"
    assert settings_custom.m2m_token == "secret-m2m-token-123"
    assert settings_custom.auth0_domain == "https://custom.auth0.com"
    assert settings_custom.iotcloud_location_id == "custom-loc-id"
    assert settings_custom.iotcloud_device_id == "custom-dev-id"
    assert settings_custom.thermostat_sensor_id == "thermostat_custom"
    assert settings_custom.switch_sensor_id == "switch_custom"
