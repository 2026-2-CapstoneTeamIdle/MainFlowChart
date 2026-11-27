"""Record billable API responses without persisting prompts, keys, or image/audio bytes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ApiUsageRecorder:
    """Append one sanitized event per provider request to a project-local JSONL file."""

    def __init__(self, project_root: Path, provider: str) -> None:
        self.path = project_root / "validation" / "api_usage" / f"{provider}.jsonl"

    def record(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"recorded_at": datetime.now(UTC).isoformat(), **event}
        with self.path.open("a", encoding="utf-8") as target:
            target.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
