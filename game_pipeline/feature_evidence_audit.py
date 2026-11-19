"""Require source-grounded evidence for feature criteria after Unity Play Mode passes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from game_pipeline.codex_cli.runner import CodexCliResult

BATCH_SIZE = 8
MAX_BATCH_ATTEMPTS = 2
DEFAULT_AUDIT_BUDGET_SECONDS = 600
DEFAULT_BATCH_TIMEOUT_SECONDS = 180


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


def _schema(count: int, expected_ids: list[str]) -> dict[str, Any]:
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
                        "criterion_id": {"type": "string", "enum": expected_ids},
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


def _audit_fingerprint(project_root: Path, pending: list[dict[str, Any]]) -> str:
    """Invalidate saved batches whenever the criteria or cited Unity sources change."""
    digest = hashlib.sha256(json.dumps(pending, ensure_ascii=False, sort_keys=True).encode())
    assets = project_root / "Assets"
    if assets.is_dir():
        for path in sorted(assets.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".cs", ".unity", ".prefab"}:
                digest.update(path.relative_to(project_root).as_posix().encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def _saved_results(
    progress_path: Path, fingerprint: str, project_root: Path
) -> dict[str, dict[str, Any]]:
    try:
        saved = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(saved, dict) or saved.get("fingerprint") != fingerprint:
        return {}
    results = saved.get("results")
    if not isinstance(results, dict):
        return {}
    verified: dict[str, dict[str, Any]] = {}
    for criterion_id, item in results.items():
        if not isinstance(criterion_id, str) or not isinstance(item, dict):
            continue
        if item.get("verification_status") in {"evidence_invalid", "audit_unavailable"}:
            continue
        evidence = _verified_sources(project_root, item.get("evidence"))
        if item.get("satisfied") is True and not evidence:
            continue
        verified[criterion_id] = {
            "satisfied": item.get("satisfied") is True,
            "evidence": evidence,
            "reason": str(item.get("reason", "")),
            "verification_status": str(
                item.get("verification_status", "verified" if evidence else "unsatisfied")
            ),
        }
    return verified


def _save_results(
    progress_path: Path, fingerprint: str, results: dict[str, dict[str, Any]]
) -> None:
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = progress_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"fingerprint": fingerprint, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(progress_path)


def _time_limit(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 60 <= value <= 7200:
        raise ValueError(f"{name} must be between 60 and 7200")
    return value


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
    deadline = time.monotonic() + _time_limit(
        "MAINFLOW_FEATURE_EVIDENCE_AUDIT_BUDGET_SECONDS", DEFAULT_AUDIT_BUDGET_SECONDS
    )
    batch_timeout = _time_limit(
        "MAINFLOW_FEATURE_EVIDENCE_AUDIT_BATCH_TIMEOUT_SECONDS", DEFAULT_BATCH_TIMEOUT_SECONDS
    )
    fingerprint = _audit_fingerprint(project_root, pending)
    progress_path = audit_root / "progress.json"
    output = _saved_results(progress_path, fingerprint, project_root)
    for offset in range(0, len(pending), BATCH_SIZE):
        batch = pending[offset : offset + BATCH_SIZE]
        expected = {item["criterion"]["criterion_id"] for item in batch}
        if expected.issubset(output):
            continue
        failure = "No audit response"
        invalid_citations: set[str] = set()
        for attempt in range(1, MAX_BATCH_ATTEMPTS + 1):
            remaining_batch = [
                item for item in batch if item["criterion"]["criterion_id"] not in output
            ]
            if not remaining_batch:
                break
            remaining_ids = {item["criterion"]["criterion_id"] for item in remaining_batch}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "Feature evidence audit time budget exhausted"
                break
            prompt = (
                "Inspect the actual Unity Assets source for each criterion below. This is a read-only "
                "audit after Unity compilation and Play Mode smoke tests passed. Do not edit files. "
                "Mark satisfied only when every behavior in that criterion is implemented and wired "
                "to the active game. A design JSON, class name, declaration, or generic smoke pass "
                "is insufficient. Cite one to three Unity C# or scene/prefab files, each with a "
                "verbatim 12+ character code excerpt. Use paths relative to the Unity project. "
                "Mark missing, partial, or uncertain behavior as satisfied=false with a clear reason. "
                "Return exactly one result for every criterion_id, in this order: "
                + ", ".join(item["criterion"]["criterion_id"] for item in remaining_batch)
                + ".\n\n"
                + json.dumps(remaining_batch, ensure_ascii=False, indent=2)
            )
            if attempt > 1:
                prompt += (
                    "\nThe preceding response had invalid IDs or unverifiable source quotes. "
                    "Open each cited file and copy an exact excerpt; return only the listed IDs."
                )
            try:
                result: CodexCliResult = client.run(
                    project_root=project_root,
                    prompt=prompt,
                    schema=_schema(len(remaining_batch), sorted(remaining_ids)),
                    audit_directory=audit_root
                    / f"batch_{offset // BATCH_SIZE + 1:02d}"
                    / f"attempt_{attempt:02d}",
                    sandbox="read-only",
                    timeout_seconds=min(remaining, batch_timeout),
                )
                rows = result.final_response.get("results")
                if not isinstance(rows, list) or len(rows) != len(remaining_batch):
                    raise ValueError("Feature evidence audit omitted required criteria")
                found = [row.get("criterion_id") for row in rows if isinstance(row, dict)]
                if (
                    len(found) != len(rows)
                    or set(found) != remaining_ids
                    or len(set(found)) != len(found)
                ):
                    raise ValueError("Feature evidence audit returned mismatched criterion IDs")
            except (RuntimeError, TimeoutError, ValueError, TypeError) as error:
                failure = str(error)
                continue
            for row in rows:
                criterion_id = row["criterion_id"]
                verified = _verified_sources(project_root, row.get("evidence"))
                if row.get("satisfied") is True and not verified:
                    invalid_citations.add(criterion_id)
                    failure = "Feature evidence audit cited missing or unverifiable Unity source"
                    continue
                output[criterion_id] = {
                    "satisfied": row.get("satisfied") is True and bool(verified),
                    "evidence": verified,
                    "reason": str(row.get("reason", "")),
                    "verification_status": (
                        "verified" if row.get("satisfied") is True and verified else "unsatisfied"
                    ),
                }
            _save_results(progress_path, fingerprint, output)
        for criterion_id in expected - output.keys():
            output[criterion_id] = {
                "satisfied": False,
                "evidence": [],
                "reason": f"Evidence audit response invalid after {MAX_BATCH_ATTEMPTS} attempts: {failure}",
                "verification_status": "evidence_invalid"
                if criterion_id in invalid_citations
                else "audit_unavailable",
            }
        if time.monotonic() >= deadline:
            break
    for item in pending:
        criterion_id = item["criterion"]["criterion_id"]
        output.setdefault(
            criterion_id,
            {
                "satisfied": False,
                "evidence": [],
                "reason": "Feature evidence audit time budget exhausted before this criterion",
                "verification_status": "audit_unavailable",
            },
        )
    return output
