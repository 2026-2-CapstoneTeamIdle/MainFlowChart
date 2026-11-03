# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MAINFLOW_WORKSPACE=/app/workspace

WORKDIR /app

RUN python -m pip install --no-cache-dir "uv>=0.9,<1.0"

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY CI/CD/LocalWeb/requirements.txt ./CI/CD/LocalWeb/requirements.txt
RUN uv pip install --python /app/.venv/bin/python -r CI/CD/LocalWeb/requirements.txt

COPY . .

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "--app-dir", "CI/CD/LocalWeb", "app:app", "--host", "0.0.0.0", "--port", "8000"]
