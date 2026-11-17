"""Require source-grounded evidence for feature criteria after Unity Play Mode passes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from game_pipeline.codex_cli.runner import CodexCliResult

BATCH_SIZE = 8


def _runner(builder: str) -> Any:
    if builder == "codex_cli":
        from game_pipeline.codex_cli.config import CodexHarnessSettings
        from game_pipeline.codex_cli.runner import CodexCliRunner

        return CodexCliRunner(CodexHarnessSettings.from_environment())
    if builder == "claude_code":
        from game_pipeline.claude_code.config import ClaudeCodeHarnessSettings
        from game_pipeline.claude_code.runner import ClaudeCodeCliRunner

        return ClaudeCodeCliRunner(ClaudeCodeHarnessSettings.from_environment())
    raise ValueError(f"Unsupported evidence audit builder: {builder}")


def _schema(count: int) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["results"],
        "properties": {
            "results": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["criterion_id", "satisfied", "evidence", "reason"],
                    "properties": {
                        "criterion_id": {"type": "string"},
                        "satisfied": {"type": "boolean"},
                        "evidence": {
                            "type": "array",
                            "maxItems": 3,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["path", "quote"],
                                "properties": {
                                    "path": {"type": "string"},
                                    "quote": {"type": "string"},
                                },
                            },
                        },
                        "reason": {"type": "string"},
                    },
                },
            }
        },
    }


def _verified_sources(project_root: Path, evidence: Any) -> list[dict[str, str]]:
    if not isinstance(evidence, list):
        return []
    verified: list[dict[str, str]] = []
    for citation in evidence[:3]:
        if not isinstance(citation, dict):
            return []
        raw_path = str(citation.get("path", "")).replace("\\", "/")
        quote = str(citation.get("quote", "")).strip()
        relative = Path(raw_path)
        if (
            not raw_path.startswith("Assets/")
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.suffix.lower() not in {".cs", ".unity", ".prefab"}
            or len(quote) < 12
        ):
            return []
        source = (project_root / relative).resolve()
        if not source.is_relative_to(project_root.resolve()) or not source.is_file():
            return []
        actual = source.read_text(encoding="utf-8", errors="replace")
        if re.sub(r"\s+", " ", quote) not in re.sub(r"\s+", " ", actual):
            return []
        verified.append({"path": raw_path, "quote": quote})
    return verified


def audit_feature_evidence(
    *,
    builder: str,
    project_root: Path,
    audit_root: Path,
    criteria: list[dict[str, Any]],
    features: list[dict[str, Any]],
    runner: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """Read-only agent audit; only cited Unity source can satisfy a missing criterion."""
    by_id = {feature["feature_id"]: feature for feature in features}
    pending = [
        {"criterion": item, "feature": by_id[item["criterion_id"][len("logic-") :]]}
        for item in criteria
        if item["criterion_id"].startswith("logic-")
        and item["criterion_id"][len("logic-") :] in by_id
    ]
    if not pending:
        return {}
    client = runner or _runner(builder)
    output: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(pending), BATCH_SIZE):
        batch = pending[offset : offset + BATCH_SIZE]
        expected = {item["criterion"]["criterion_id"] for item in batch}
        prompt = (
            "Inspect the actual Unity Assets source for each criterion below. This is a read-only "
            "audit after Unity compilation and Play Mode smoke tests passed. Do not edit files. "
            "Mark satisfied only when every behavior in that criterion is implemented and wired "
            "to the active game. A design JSON, class name, declaration, or generic smoke pass "
            "is insufficient. Cite one to three Unity C# or scene/prefab files, each with a "
            "verbatim 12+ character code excerpt. Use paths relative to the Unity project. "
            "Mark missing, partial, or uncertain behavior as satisfied=false with a clear reason. "
            "Return exactly one result for every criterion_id.\n\n"
            + json.dumps(batch, ensure_ascii=False, indent=2)
        )
        result: CodexCliResult = client.run(
            project_root=project_root,
            prompt=prompt,
            schema=_schema(len(batch)),
            audit_directory=audit_root / f"batch_{offset // BATCH_SIZE + 1:02d}",
            sandbox="read-only",
        )
        rows = result.final_response.get("results")
        if not isinstance(rows, list) or len(rows) != len(batch):
            raise ValueError("Feature evidence audit omitted required criteria")
        found = [row.get("criterion_id") for row in rows if isinstance(row, dict)]
        if len(found) != len(rows) or set(found) != expected or len(set(found)) != len(found):
            raise ValueError("Feature evidence audit returned mismatched criterion IDs")
        for row in rows:
            verified = _verified_sources(project_root, row.get("evidence"))
            satisfied = row.get("satisfied") is True and bool(verified)
            output[row["criterion_id"]] = {
                "satisfied": satisfied,
                "evidence": verified,
                "reason": str(row.get("reason", "")),
            }
    return output
