FROM ghcr.io/astral-sh/uv:0.10.9 AS uv
FROM python:3.12-slim AS runtime
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH=/app/.venv/bin:$PATH
COPY pyproject.toml uv.lock README.md ./
COPY backend/src backend/src
COPY scripts scripts
RUN uv sync --locked --no-dev --no-editable
COPY backend/alembic.ini backend/alembic.ini
COPY backend/migrations backend/migrations
RUN useradd --uid 10001 --create-home polybot
USER polybot
ENTRYPOINT ["python", "-m", "api.deployment"]
