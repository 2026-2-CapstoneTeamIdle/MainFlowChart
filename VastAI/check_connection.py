"""Check a role-specific Vast.ai vLLM endpoint without exposing its API key."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

from VastAI.settings import VastAIRole, load_vastai_settings


def check_connection(role: VastAIRole) -> dict[str, object]:
    settings = load_vastai_settings(role)
    headers = {"Accept": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    request = urllib.request.Request(f"{settings.base_url}/models", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Vast.ai {role} endpoint returned HTTP {error.code}") from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not connect to the Vast.ai {role} endpoint") from error

    models = [
        item.get("id")
        for item in payload.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    return {
        "role": role,
        "base_url": settings.base_url,
        "configured_model": settings.model,
        "available_models": models,
        "model_registered": settings.model in models,
        "authenticated": settings.api_key is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("coder", "vlm", "image"), default="coder")
    arguments = parser.parse_args()
    report = check_connection(arguments.role)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["model_registered"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
