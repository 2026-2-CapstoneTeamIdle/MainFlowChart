# syntax=docker/dockerfile:1
# Build context: repository root (see compose.yaml). The image contains the
# whole MainFlowChart workflow so the web server can run the LangGraph graph.
FROM python:3.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    MAINFLOW_WORKSPACE=/app/workspace

WORKDIR /app

# Same lockfile as the workflow image, plus the "web" dependency group (FastAPI).
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --group web --no-install-project

COPY . .

EXPOSE 8000

CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app:app", "--app-dir", "CI/CD/LocalWeb", "--host", "0.0.0.0", "--port", "8000"]
