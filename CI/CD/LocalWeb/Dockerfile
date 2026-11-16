# syntax=docker/dockerfile:1
ARG UNITY_EDITOR_IMAGE=unityci/editor:ubuntu-6000.0.71f1-webgl-3

FROM python:3.11-slim-bookworm AS python-runtime

FROM node:22-bookworm-slim AS codex-cli

ARG CODEX_CLI_VERSION=0.167.2
RUN npm install --global "@openai/codex@${CODEX_CLI_VERSION}"

FROM ${UNITY_EDITOR_IMAGE}

USER root

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MAINFLOW_WORKSPACE=/app/workspace \
    CODEX_HOME=/home/mainflow/.codex \
    MAINFLOW_CODEX_CLI_PATH=/usr/local/bin/codex \
    UNITY_EDITOR_PATH=/opt/unity/Editor/Unity \
    UNITY_CLI_HOME=/opt/unity-cli \
    UNITY_NO_CONSENT_PROMPT=1 \
    DISPLAY=:99 \
    HOME=/home/mainflow

WORKDIR /app

COPY --from=python-runtime /usr/local /usr/local
COPY --from=codex-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-cli /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl git xvfb \
    && rm -rf /var/lib/apt/lists/* \
    && python -c "import ssl, sqlite3; print('Python runtime ready')" \
    && test -x /opt/unity/Editor/Unity \
    && test -d /opt/unity/Editor/Data/PlaybackEngines/WebGLSupport

RUN curl -fsSL https://unity.com/install.sh -o /tmp/install-unity-cli.sh \
    && bash /tmp/install-unity-cli.sh \
    && rm -f /tmp/install-unity-cli.sh \
    && /opt/unity-cli/bin/unity --version

RUN python -m pip install --no-cache-dir "uv>=0.9,<1.0"

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY CI/CD/LocalWeb/requirements.txt ./CI/CD/LocalWeb/requirements.txt
RUN uv pip install --python /app/.venv/bin/python -r CI/CD/LocalWeb/requirements.txt

RUN id mainflow >/dev/null 2>&1 \
    || useradd --create-home --uid 10001 --shell /bin/bash mainflow

COPY --chown=mainflow:mainflow . .

RUN mkdir -p \
        /app/workspace \
        /home/mainflow/.cache/unity3d \
        /home/mainflow/.codex \
        /home/mainflow/.config \
        /home/mainflow/.local/share/unity3d/Unity \
    && printf 'cli_auth_credentials_store = "file"\n' > /home/mainflow/.codex/config.toml \
    && chmod +x /app/CI/CD/LocalWeb/docker-entrypoint.sh \
    && chown -R mainflow:mainflow /app /home/mainflow

ENV PATH="/opt/unity-cli/bin:/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app

USER mainflow

EXPOSE 8000

ENTRYPOINT ["/app/CI/CD/LocalWeb/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "--app-dir", "CI/CD/LocalWeb", "app:app", "--host", "0.0.0.0", "--port", "8000"]
