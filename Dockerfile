FROM python:3.14-slim

# Pinned uv binary from the official Astral distribution (bump deliberately)
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

WORKDIR /app

# Enable bytecode compilation, copy-mode installs and unbuffered stdout/stderr output
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Copy dependency definition files first for Docker layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source code (.dockerignore keeps .env and dev files out)
COPY README.md ./
COPY src ./src

# Install the project into the virtual environment
RUN uv sync --frozen --no-dev

# Run as an unprivileged user
RUN useradd --system --uid 10001 --home-dir /app app \
    && mkdir -p /app/logs \
    && chown -R app:app /app/logs
USER app

# Run the installed entrypoint directly (no re-sync at container start)
ENTRYPOINT ["/app/.venv/bin/iotcloud-health"]
