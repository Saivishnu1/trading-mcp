FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Layer-cache: install deps before copying source so a code change
# doesn't re-download all packages.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-install-project --no-dev --frozen

COPY src/ src/
COPY ui/ ui/
RUN uv sync --no-dev --frozen

EXPOSE 8000

# Call the installed entry point directly — no `uv run` sync overhead.
# $PORT is injected by Render/Railway; falls back to 8000 locally.
CMD ["sh", "-c", "/app/.venv/bin/zerodha-mcp"]
