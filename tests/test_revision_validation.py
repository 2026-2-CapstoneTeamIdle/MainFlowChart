from unittest.mock import Mock, patch

import pytest

from game_pipeline.unity_project_validator import UnityProjectValidator, UnityValidationOutcome
from mainflow import revise_project


@pytest.mark.parametrize("compile_passed", [True, False])
def test_revision_requires_compile_then_play_mode_without_scene_reassembly(
    tmp_path, compile_passed
):
    validator = UnityProjectValidator(unity_editor=tmp_path / "Unity.exe")
    outcome = UnityValidationOutcome()
    validator._add_check(outcome, "unity.source_compile", compile_passed, "compile")
    with (
        patch.object(validator, "compile_sources", return_value=outcome),
        patch.object(validator, "_run_runtime_tests") as runtime,
        patch.object(validator, "_run_unity_validation") as assemble,
    ):
        result = validator.validate_revision(tmp_path)
    assert result is outcome
    assert runtime.call_count == int(compile_passed)
    assemble.assert_not_called()


@pytest.mark.parametrize("passed", [True, False])
def test_revision_worker_does_not_trust_agent_completion(tmp_path, passed):
    import json

    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"builder": "codex_cli", "project_root": str(tmp_path), "messages": []})
    )
    runner = Mock()
    runner.run.return_value.final_response = {"status": "completed", "summary": "수정했습니다."}
    report = {
        "status": "passed" if passed else "failed",
        "checks": [{"passed": passed, "message": "Compiler error CS0029"}],
    }
    with (
        patch.object(revise_project.sys, "argv", ["revise", str(request)]),
        patch("game_pipeline.codex_cli.runner.CodexCliRunner", return_value=runner),
        patch.object(revise_project, "validate_revision", return_value=report),
    ):
        revise_project.main()
    result = json.loads((tmp_path / "revision_result.json").read_text(encoding="utf-8"))
    assert result["status"] == ("completed" if passed else "failed")
    assert result["validation_status"] == report["status"]
    if not passed:
        assert "CS0029" in result["summary"]
