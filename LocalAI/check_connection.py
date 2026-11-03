"""Check that LocalAI exposes a model with the context expected by MainFlow."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL = "qwen2.5-coder-7b-q5-k-m"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check the LocalAI model endpoint.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LOCAL_LLM_BASE_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("LOCAL_LLM_MODEL", DEFAULT_MODEL),
    )
    parser.add_argument(
        "--context-tokens",
        type=int,
        default=int(os.environ.get("LOCAL_LLM_CONTEXT_TOKENS", "16384")),
        help="Expected effective model context reported by LocalAI.",
    )
    return parser.parse_args()


def _get_json(url: str) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    api_key = os.environ.get("LOCAL_LLM_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"LocalAI returned HTTP status {error.code}") from None
    except urllib.error.URLError as error:
        raise RuntimeError("Could not connect to LocalAI") from error


def run_check(
    base_url: str,
    expected_model: str,
    expected_context_tokens: int | None = None,
) -> dict[str, Any]:
    if expected_context_tokens is not None and expected_context_tokens < 1:
        raise ValueError("expected_context_tokens must be greater than zero")
    payload = _get_json(f"{base_url.rstrip('/')}/models/capabilities")
    model_entries = [item for item in payload.get("data", []) if isinstance(item, dict)]
    model_names = sorted(item["id"] for item in model_entries if isinstance(item.get("id"), str))
    selected_model = next(
        (item for item in model_entries if item.get("id") == expected_model),
        None,
    )
    actual_context_tokens = _context_tokens(selected_model)
    if selected_model is None:
        status = "model_not_ready"
    elif expected_context_tokens is not None and actual_context_tokens is None:
        status = "context_unavailable"
    elif expected_context_tokens is not None and actual_context_tokens != expected_context_tokens:
        status = "context_mismatch"
    else:
        status = "passed"
    return {
        "status": status,
        "base_url": base_url,
        "expected_model": expected_model,
        "expected_context_tokens": expected_context_tokens,
        "actual_context_tokens": actual_context_tokens,
        "available_models": model_names,
    }


def _context_tokens(model: dict[str, Any] | None) -> int | None:
    if model is None:
        return None
    candidates = [
        model.get("context_size"),
        model.get("context_length"),
    ]
    for container_name in ("capabilities", "details"):
        container = model.get(container_name)
        if isinstance(container, dict):
            candidates.extend((container.get("context_size"), container.get("context_length")))
    return next(
        (
            value
            for value in candidates
            if isinstance(value, int) and not isinstance(value, bool) and value > 0
        ),
        None,
    )


def main() -> None:
    args = _parse_args()
    try:
        report = run_check(args.base_url, args.model, args.context_tokens)
    except (RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
