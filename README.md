# IotCloud-Health-Check

Synthetic health monitoring and alerting service for the IotCloud platform. Built with a headless **Machine-to-Machine (M2M)** architecture using `X-M2M-Token`, designed to run on a dedicated monitoring host and communicate with backend services over WireGuard VPN.

## Core Synthetic Health Checks

1. **Auth0 OIDC Infrastructure Probe & Internal API (`check_api`)**:
   - Validates Auth0 OIDC Discovery endpoint (`/.well-known/openid-configuration`) and JWKS endpoint (`/.well-known/jwks.json`) without credentials/passwords.
   - Verifies Internal API connectivity and authentication.
2. **Data Ingestion & TimescaleDB Persistence (`check_ingestion`)**:
   - Queries recent time-series data points from TimescaleDB via Internal API (`POST /sensors/{sensor_id}/data`).
   - Verifies that data points have arrived within the last 15 minutes (threshold: 900s, Virtual Poller 300s interval).
3. **Thermostat Automations & Actuation Roundtrip (`check_thermostat`)**:
   - Verifies thermostat controller discovery (`GET /thermostats`).
   - Dispatches a target setpoint change (`POST /sensors/{sensor_id}/actions/setpoint`).
   - Verifies live Redis state snapshot reflection (`GET /sensors/{sensor_id}/snapshot`).
4. **State-Transition Telegram Alerting**:
   - Dispatches tailored HTML alerts to Telegram exclusively on state changes (`HEALTHY -> FAILING`).
   - Dispatches recovery notification on recovery (`FAILING -> HEALTHY`).
   - Suppresses redundant notifications while status is unchanged.

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
