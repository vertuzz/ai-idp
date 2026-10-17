FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./

RUN uv sync --frozen --no-dev
ENV UV_NO_SYNC=1 UV_NO_DEV=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["uv", "run", "--locked", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"]

CMD ["uv", "run", "uvicorn", "ai_idp.adapters.inbound.http.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
