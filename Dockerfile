FROM python:3.14-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    WEBGENT_IN_DOCKER=1 \
    WEBGENT_SERVER_HOST=0.0.0.0 \
    WEBGENT_HEADLESS=true \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md prompt.md settings.toml ./
COPY webgent ./webgent

RUN uv sync --frozen --no-dev \
    && uv run playwright install --with-deps chromium \
    && mkdir -p /app/profile /app/media /app/registry /app/mitmproxy

EXPOSE 3333

CMD ["webgent"]
