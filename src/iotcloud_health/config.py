"""Configuration settings for IotCloud Health Check Service."""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Internal M2M API Settings
    internal_api_url: str = Field(
        default="http://localhost:8001",
        validation_alias=AliasChoices(
            "INTERNAL_API_URL", "internal_api_url", "INTERNAL_API_BASE_URL"
        ),
        description="Internal M2M API base URL",
    )
    m2m_token: str = Field(
        default="",
        validation_alias=AliasChoices("M2M_TOKEN", "m2m_token", "X_M2M_TOKEN", "x_m2m_token"),
        description="Machine-to-machine authentication token",
    )
    auth0_domain: str = Field(
        default="https://iotauth.eu.auth0.com",
        validation_alias=AliasChoices("AUTH0_DOMAIN", "auth0_domain"),
        description="Auth0 base domain",
    )

    # Target Location, Device & Sensor Settings (Demo Virtual Suite)
    iotcloud_location_id: str = Field(
        default="5d0000000000000000000001",
        validation_alias=AliasChoices(
            "IOTCLOUD_LOCATION_ID", "location_id", "LOCATION_ID"
        ),
        description="Target location ID",
    )
    iotcloud_device_id: str = Field(
        default="demo_virtual_hub_01",
        validation_alias=AliasChoices(
            "IOTCLOUD_DEVICE_ID", "device_id", "DEVICE_ID"
        ),
        description="Target device ID",
    )
    thermostat_sensor_id: str = Field(
        default="demo_thermostat",
        validation_alias=AliasChoices("THERMOSTAT_SENSOR_ID", "thermostat_sensor_id"),
        description="Thermostat sensor ID for ingestion and actuation checks",
    )
    switch_sensor_id: str = Field(
        default="demo_switch",
        validation_alias=AliasChoices("SWITCH_SENSOR_ID", "switch_sensor_id"),
        description="Switch sensor ID",
    )

    # Telegram Alert Notifications
    telegram_token: str = Field(
        default="",
        validation_alias=AliasChoices("TELEGRAM_TOKEN", "telegram_token"),
        description="Telegram bot token",
    )
    telegram_chat_id: int = Field(
        default=0,
        validation_alias=AliasChoices("TELEGRAM_CHAT_ID", "telegram_chat_id"),
        description="Telegram chat ID for alert notifications",
    )

    # Service Settings
    check_interval_seconds: int = Field(
        default=300,
        validation_alias=AliasChoices("CHECK_INTERVAL_SECONDS", "check_interval_seconds"),
        description="Interval between health check executions in seconds",
    )
    log_path: str = Field(
        default="logs/healthCheck.log",
        validation_alias=AliasChoices("LOG_PATH", "log_path"),
        description="Log file path",
    )
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("LOG_LEVEL", "log_level"),
        description="Logging level",
    )


settings = Settings()
