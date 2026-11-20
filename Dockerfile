# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
# The same uv minor version that wrote uv.lock; an older uv may refuse it with --locked.
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
# The system Python of this image only: a downloaded one would not exist in the runtime stage.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home --uid 1000 bot
WORKDIR /app
COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/src ./src
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
RUN mkdir /app/storage && chown bot:bot /app/storage
USER bot
CMD ["python", "-m", "nutrition_bot"]
