FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifest first for layer caching
COPY pyproject.toml .

# Install dependencies (no project, just deps)
RUN uv sync --no-install-project --no-dev

# Copy source
COPY src/ src/

# Install the project itself
RUN uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "zerodha-mcp"]
