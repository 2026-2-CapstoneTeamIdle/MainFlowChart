# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    MAINFLOW_WORKSPACE=/app/workspace

WORKDIR /app

# Keep dependency installation cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

CMD ["/app/.venv/bin/python", "run_flow.py", "--image-style", "Pixel Art", "--genre", "Action", "--quality", "Medium"]
