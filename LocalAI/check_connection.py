"""Check that the configured LocalAI endpoint exposes the selected model alias."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL = "gemma4-e2b-q4"


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


def run_check(base_url: str, expected_model: str) -> dict[str, Any]:
    payload = _get_json(f"{base_url.rstrip('/')}/models")
    model_names = sorted(
        item["id"]
        for item in payload.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    )
    return {
        "status": "passed" if expected_model in model_names else "model_not_ready",
        "base_url": base_url,
        "expected_model": expected_model,
        "available_models": model_names,
    }


def main() -> None:
    args = _parse_args()
    try:
        report = run_check(args.base_url, args.model)
    except RuntimeError as error:
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
