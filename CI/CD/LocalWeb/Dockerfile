# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS codex-cli

ARG CODEX_CLI_VERSION=0.167.2
RUN npm install --global "@openai/codex@${CODEX_CLI_VERSION}"

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MAINFLOW_WORKSPACE=/app/workspace \
    CODEX_HOME=/home/mainflow/.codex \
    MAINFLOW_CODEX_CLI_PATH=/usr/local/bin/codex \
    HOME=/home/mainflow

WORKDIR /app

COPY --from=codex-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-cli /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex

RUN python -m pip install --no-cache-dir "uv>=0.9,<1.0"

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY CI/CD/LocalWeb/requirements.txt ./CI/CD/LocalWeb/requirements.txt
RUN uv pip install --python /app/.venv/bin/python -r CI/CD/LocalWeb/requirements.txt

RUN useradd --create-home --uid 10001 --shell /bin/bash mainflow

COPY --chown=mainflow:mainflow . .

RUN mkdir -p /app/workspace /home/mainflow/.codex \
    && printf 'cli_auth_credentials_store = "file"\n' > /home/mainflow/.codex/config.toml \
    && chown -R mainflow:mainflow /app /home/mainflow

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app

USER mainflow

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "--app-dir", "CI/CD/LocalWeb", "app:app", "--host", "0.0.0.0", "--port", "8000"]
