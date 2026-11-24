# IotCloud-Health-Check

Synthetic health monitoring and alerting service for the IotCloud platform. Built with a headless **Machine-to-Machine (M2M)** architecture using `X-M2M-Token`, designed to run on a dedicated monitoring host and communicate with backend services over WireGuard VPN.

## Core Synthetic Health Checks

Every cycle (default 5 minutes) runs these checks in order:

1. **Public API & SSL (`public_api`)**: probes `PUBLIC_API_URL` externally, expects HTTP 200 (and `"status": "healthy"` if the body reports a status), and alerts when the TLS certificate is invalid, expired, or within `SSL_MIN_DAYS_VALID` days of expiry.
2. **MQTT over WSS (`mqtt_wss`)**: the app's path. Validates the broker's TLS certificate, performs a WebSocket upgrade with the `mqtt` subprotocol and verifies the `101` response.
3. **MQTT device login (`mqtt_device`)**: the devices' path. Fetches the demo device's MQTT token (`GET /devices/{IOTCLOUD_DEVICE_ID}/mqtt-auth`, cached), logs in to EMQX on plain `MQTT_TCP_HOST:MQTT_TCP_PORT` with a unique client ID and subscribes to one of its own topics. This exercises EMQX plus api-internal's `/mqtt/emqx/authn` (CONNECT) and `/mqtt/emqx/authz` (SUBSCRIBE) hooks.
4. **OTA server (`ota`)**: GETs `OTA_URL` without certificate verification (the cert is self-signed and may be pinned by devices). Any non-5xx answer is healthy; 5xx means nginx cannot reach the `ota` container.
5. **Auth0 OIDC & Internal API (`api`)**: validates the OIDC discovery document (issuer) and that JWKS returns signing keys, then checks Internal API connectivity and `X-M2M-Token` auth.
6. **Data Ingestion & TimescaleDB (`ingestion`)**: queries the last 30 minutes of telemetry (`POST /sensors/{sensor_id}/data`) and alerts if there is none or the newest point is older than 15 minutes.
7. **Thermostat Actuation Roundtrip (`thermostat`)**: verifies discovery (`GET /thermostats`), toggles the demo thermostat setpoint between 21.5 and 22.0 and confirms it is reflected in the Redis snapshot within ~5s. Reports a separate "Demo Device Offline" alert when the snapshot says the device is offline.
8. **Watched devices online (`devices`)**: one `POST /sensors/snapshot` for `WATCHED_SENSOR_IDS`; each sensor whose device's MQTT status is not `online` gets its own alert and recovery (`device:<sensor_id>`). Skipped when the list is empty.

> The demo device (`demo_virtual_hub_01` with `demo_thermostat` / `demo_switch`) is a **virtual device run by IotCloud2's `automation_runner`** (virtual runtime). It connects to EMQX like a real device and publishes telemetry every 5 minutes, so the ingestion and thermostat checks cover: Internal API → Redis → Rust Gateway → EMQX → automation_runner → EMQX → Rust Gateway → TimescaleDB/Redis.

### Alerting

- Telegram alerts are sent only on state transitions (`HEALTHY → FAILING`, `FAILING → HEALTHY`).
- A check must fail `ALERT_AFTER_FAILURES` consecutive cycles (default **2**) before alerting, which filters one-off network blips. Set it to `1` for immediate alerts.
- Transitions from one cycle are combined: an outage that trips several checks sends **one** "N checks failing" message, and one "N checks recovered" message when it clears. Messages list anything that is still failing.
- The headline is the failure type (e.g. **Internal API Down**), followed by the affected check, the time it started failing (in `ALERT_TIMEZONE`, default `Europe/Madrid`) and a short cause such as `[Errno 111] Connection refused`. Recovery messages include the downtime.
- If Telegram delivery fails, the alert is retried on the next cycle (state is only updated once delivered).
- Remote error bodies are truncated so alerts always fit Telegram's 4096-character limit, and the bot token / M2M token are redacted from all logs.

---

## Tech Stack & Architecture

- **Python**: 3.14+
- **Package & Environment Manager**: [uv](https://docs.astral.sh/uv/)
- **Linter & Formatter**: [Ruff](https://docs.astral.sh/ruff/)
- **Type Checker**: [Pyright](https://github.com/microsoft/pyright)
- **Settings & Validation**: [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) reading from `.env`
- **Testing**: [pytest](https://docs.pytest.org/) with [pytest-mock](https://github.com/pytest-dev/pytest-mock)
- **Containerization**: Multi-stage `Dockerfile` with `uv` and `docker-compose.yml`

---

## Quick Start

### 1. Prerequisites

Ensure [uv](https://docs.astral.sh/uv/) and Python 3.14 are installed:
```bash
uv --version
```

### 2. Install Dependencies

Clone the repository and synchronize the virtual environment:
```bash
uv sync
```

### 3. Environment Configuration

Copy the sample environment file and populate your credentials:
```bash
cp .env.example .env
```

Environment variables in `.env`:
| Variable | Default | Description |
|---|---|---|
| `INTERNAL_API_URL` | `http://api-internal.iotcloud_healthcheck:8001` | Internal M2M API Base URL (`http://api-internal.iotcloud_healthcheck:8001` over WireGuard, or `http://localhost:8001` locally) |
| `M2M_TOKEN` | *(required)* | Secret token passed via `X-M2M-Token` header |
| `AUTH0_DOMAIN` | `https://iotauth.eu.auth0.com` | Auth0 domain for OIDC discovery probe |
| `IOTCLOUD_LOCATION_ID` | `5d0000000000000000000001` | Target demo location ID |
| `IOTCLOUD_DEVICE_ID` | `demo_virtual_hub_01` | Target demo virtual smart hub ID |
| `THERMOSTAT_SENSOR_ID` | `demo_thermostat` | Target thermostat sensor ID |
| `SWITCH_SENSOR_ID` | `demo_switch` | Target switch sensor ID |
| `TELEGRAM_TOKEN` | *(required)* | Telegram Bot token for sending alert notifications |
| `TELEGRAM_CHAT_ID` | *(required)* | Telegram chat ID for destination alerts |
| `PUBLIC_API_URL` | `https://api.iotcloud.es/api/v2/health` | Public API health endpoint probed externally |
| `MQTT_WSS_URL` | `wss://mqtt.iotcloud.es/mqtt` | MQTT broker WebSocket Secure URL |
| `MQTT_TCP_HOST` | `mqtt.iotcloud.es` | Host devices use for plain MQTT |
| `MQTT_TCP_PORT` | `1883` | Plain MQTT port devices use |
| `OTA_URL` | `https://ota.iotcloud.es/` | OTA firmware server |
| `WATCHED_SENSOR_IDS` | *(empty)* | Comma-separated sensor IDs whose devices must stay online |
| `SSL_MIN_DAYS_VALID` | `7` | Alert when a certificate expires within this many days |
| `ALERT_AFTER_FAILURES` | `2` | Consecutive failed cycles before a Telegram alert is sent |
| `ALERT_TIMEZONE` | `Europe/Madrid` | Timezone for times shown in alerts |
| `CHECK_INTERVAL_SECONDS` | `300` | Health check cycle interval in seconds |
| `LOG_PATH` | `logs/healthCheck.log` | Rotating log file destination |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Running Locally

Run the health check service via the entrypoint script:
```bash
uv run iotcloud-health
```
or via module execution:
```bash
uv run python -m iotcloud_health.main
```

---

## Development & Code Quality

### Lint and Format Checks
```bash
# Check code with Ruff
uv run ruff check .

# Automatically apply safe fixes
uv run ruff check . --fix

# Format code with Ruff
uv run ruff format .

# Check formatting without modifying
uv run ruff format --check .
```

### Type Checking
```bash
uv run pyright
```

### Unit Tests
```bash
uv run pytest -v
```

---

## Docker & Deployment

The image runs as an unprivileged user (uid `10001`). `.env` is never copied into the image (see `.dockerignore`); it is injected at runtime via `env_file`. If the mounted `./logs` directory is not writable by that user, the service logs to stdout only (`chown 10001 logs` to enable the file log).

### Build and Run with Docker Compose
```bash
docker compose up -d --build
```

### View Logs
```bash
docker compose logs -f
```

### Stop Service
```bash
docker compose down
```
