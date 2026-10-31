#!/usr/bin/env bash
set -euo pipefail

: "${VASTAI_MODEL:?Set VASTAI_MODEL to a Hugging Face model ID or local model path}"

VASTAI_ROLE="${VASTAI_ROLE:-coder}"
VASTAI_PORT="${VASTAI_PORT:-8000}"
VASTAI_SERVED_MODEL="${VASTAI_SERVED_MODEL:-mainflow-${VASTAI_ROLE}}"
VASTAI_MAX_MODEL_LEN="${VASTAI_MAX_MODEL_LEN:-32768}"

args=(
  serve "${VASTAI_MODEL}"
  --host 0.0.0.0
  --port "${VASTAI_PORT}"
  --served-model-name "${VASTAI_SERVED_MODEL}"
  --max-model-len "${VASTAI_MAX_MODEL_LEN}"
)

if [[ -n "${VASTAI_INFERENCE_API_KEY:-}" ]]; then
  args+=(--api-key "${VASTAI_INFERENCE_API_KEY}")
fi

if [[ -n "${VASTAI_TOOL_CALL_PARSER:-}" ]]; then
  args+=(--enable-auto-tool-choice --tool-call-parser "${VASTAI_TOOL_CALL_PARSER}")
fi

if [[ "${VASTAI_VLLM_MODE:-generate}" == "omni" ]]; then
  args+=(--omni)
fi

exec vllm "${args[@]}" "$@"
