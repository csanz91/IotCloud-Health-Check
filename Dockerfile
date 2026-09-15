FROM python:3.14-slim

# Install uv binary from official Astral distribution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Enable bytecode compilation and unbuffered stdout/stderr output
ENV UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy dependency definition files first for Docker layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source code
COPY . .

# Install the project into the virtual environment
RUN uv sync --frozen --no-dev

# Create log directory
RUN mkdir -p logs

ENTRYPOINT ["uv", "run", "iotcloud-health"]
