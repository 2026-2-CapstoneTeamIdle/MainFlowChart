"""Apply a conversational edit to an existing project using the selected CLI agent."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path


def validate_revision(project_root: Path, audit: Path) -> dict:
    from game_pipeline.unity_project_validator import UnityProjectValidator

    print("[CHAT] 수정된 프로젝트의 Unity 컴파일·Play Mode를 검증합니다.", flush=True)
    validator = UnityProjectValidator(
        mode="required",
        unity_editor=os.environ.get("UNITY_EDITOR_PATH") or None,
    )
    outcome = validator.validate_revision(project_root)
    report = {**asdict(outcome), "status": outcome.status}
    (audit / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    request_file = Path(sys.argv[1])
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if request["builder"] == "claude_code":
        from game_pipeline.claude_code.config import ClaudeCodeHarnessSettings
        from game_pipeline.claude_code.runner import ClaudeCodeCliRunner

        runner = ClaudeCodeCliRunner(ClaudeCodeHarnessSettings.from_environment())
    else:
        from game_pipeline.codex_cli.config import CodexHarnessSettings
        from game_pipeline.codex_cli.runner import CodexCliRunner

        runner = CodexCliRunner(CodexHarnessSettings.from_environment())
    prompt = (
        "Modify this existing Unity project according to the latest user request. "
        "Read the current source and preserve existing gameplay and assets. "
        "Use the earlier conversation as context. Make the changes, inspect affected API types, "
        "and compile/test with available Unity tooling. Report honestly which checks ran and "
        "any pending validation. Never claim a build passed without evidence. "
        "Do not delete the project or edit unrelated directories. Reply in Korean.\n"
        + json.dumps(
            {
                "original_request": request.get("original_request"),
                "failure_evidence": request.get("failure_evidence"),
                "conversation": request["messages"],
            },
            ensure_ascii=False,
        )
    )
    result = runner.run(
        project_root=Path(request["project_root"]),
        prompt=prompt,
        schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["completed", "failed"]},
                "summary": {"type": "string"},
            },
            "required": ["status", "summary"],
            "additionalProperties": False,
        },
        audit_directory=request_file.parent / "agent",
    )
    response = dict(result.final_response)
    response["validation_status"] = "not_run"
    if response.get("status") == "completed":
        report = validate_revision(Path(request["project_root"]), request_file.parent)
        response["validation_status"] = report["status"]
        if report["status"] != "passed":
            response["status"] = "failed"
            failures = [check["message"] for check in report["checks"] if not check["passed"]]
            response["summary"] += "\nUnity 검증 실패: " + "; ".join(failures)
    (request_file.parent / "revision_result.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(response.get("summary", ""), flush=True)


if __name__ == "__main__":
    main()
