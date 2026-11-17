"""Run an independent AI quality audit after all deterministic validation."""

from __future__ import annotations

import os
from pathlib import Path
from time import monotonic
from traceback import format_exc
from typing import Any, cast

from game_pipeline import (
    create_game_quality_validator_from_environment,
    resolve_feature_provider_from_environment,
    run_claude_code_quality_review,
    run_codex_quality_review,
)
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    GameValidatorAIAgentInput,
    GameValidatorAIAgentOutput,
    GameValidatorAIResult,
)
from mainflow.nodes._common import log


def game_quality_validator_node(
    state: GameValidatorAIAgentInput,
) -> GameValidatorAIAgentOutput:
    """Evaluate the completed game without allowing the AI to modify it."""

    log("독립 Validator AI가 요구사항, 플레이 흐름, 콘텐츠와 검증 증거를 종합 평가합니다.")
    manager = ArtifactManager()
    refreshed_final_validation = None
    keys = [
        "parsed_request",
        "logic_analysis",
        "game_logic_draft",
        "game_validation_result",
        "image_validation_result",
        "sound_validation_result",
        "integrated_game",
        "final_validation_result",
    ]
    if "visual_validation_result" in state:
        keys.append("visual_validation_result")
    try:
        evidence: dict[str, Any] = {}
        for key in keys:
            reference = state[key]
            if reference["project_id"] != state["project_id"]:
                raise ValueError(f"Cross-project Validator AI input: {key}")
            evidence[key] = manager.read_json(reference)

        final_result = evidence["final_validation_result"]
        if final_result.get("status") != "passed":
            report = _hard_failure_report(evidence)
        elif os.environ.get("MAINFLOW_GAME_VALIDATOR_ENABLED", "1").strip().lower() in {
            "0",
            "false",
            "no",
            "off",
        }:
            report = _disabled_report()
        elif os.environ.get("MAINFLOW_GAME_BUILDER", "").strip().lower() == "codex_cli":
            report = cast(
                GameValidatorAIResult,
                run_codex_quality_review(
                    project_root=manager.ensure_project(state["project_id"]),
                    project_id=state["project_id"],
                    evidence=evidence,
                ),
            )
        elif os.environ.get("MAINFLOW_GAME_BUILDER", "").strip().lower() == "claude_code":
            report = cast(
                GameValidatorAIResult,
                run_claude_code_quality_review(
                    project_root=manager.ensure_project(state["project_id"]),
                    project_id=state["project_id"],
                    evidence=evidence,
                ),
            )
        else:
            provider = resolve_feature_provider_from_environment()
            validator = create_game_quality_validator_from_environment(
                state["project_id"], provider=provider
            )
            ai_report = validator.evaluate(state["project_id"], evidence)
            report = cast(
                GameValidatorAIResult, {"contract_version": CONTRACT_VERSION, **ai_report}
            )
        report = _normalize_placeholder_visual_limitation(
            report, final_result, evidence.get("visual_validation_result")
        )
        report = _normalize_duration_limitation(report, final_result)
        if (
            final_result.get("status") == "passed"
            and report.get("status") in {"needs_revision", "failed"}
            and os.environ.get("MAINFLOW_GAME_BUILDER", "").strip().lower()
            in {"codex_cli", "claude_code"}
        ):
            report = _repair_and_review_quality(
                state["project_id"], manager, evidence, report, state=state
            )
            if report.get("status") == "passed":
                # Quality repair changes the Unity source after the original archive was built.
                # Re-run the hard gate and package that exact repaired tree before returning success.
                from mainflow.nodes.final_validation import final_validation_node

                log("품질 수정본을 최종 검증하고 배포 ZIP을 다시 생성합니다.")
                refreshed_output = final_validation_node(
                    state,
                    artifact_variant="post_quality",
                )
                refreshed_final_validation = refreshed_output["final_validation_result"]
                evidence["final_validation_result"] = manager.read_json(refreshed_final_validation)
                if "game_validation_result" in refreshed_output:
                    evidence["game_validation_result"] = manager.read_json(
                        refreshed_output["game_validation_result"]
                    )
                if evidence["final_validation_result"].get("status") != "passed":
                    report = _hard_failure_report(evidence)
    except Exception as error:  # noqa: BLE001 - preserve a report at the final workflow boundary
        diagnostic = f"{type(error).__name__}: {error}"
        log(f"[ERROR] 독립 품질 검증 중 예외가 발생했습니다: {diagnostic}")
        try:
            manager.write_json(
                state["project_id"],
                "validation",
                "game_quality_validator_error.json",
                {"error": diagnostic, "traceback": format_exc()},
                producer="game_quality_validator",
            )
        except OSError as record_error:
            log(
                "[ERROR] 품질 검증 예외의 상세 기록을 저장하지 못했습니다: "
                f"{type(record_error).__name__}: {record_error}"
            )
        report = _execution_failure_report(error)

    output: GameValidatorAIAgentOutput = {
        "game_validator_ai_result": manager.write_json(
            state["project_id"],
            "validation",
            "game_validator_ai_result.json",
            report,
            producer="game_quality_validator",
        )
    }
    if refreshed_final_validation is not None:
        output["final_validation_result"] = refreshed_final_validation
    return output


def _repair_and_review_quality(
    project_id: str,
    manager: ArtifactManager,
    evidence: dict[str, Any],
    initial_report: GameValidatorAIResult,
    *,
    state: GameValidatorAIAgentInput | None = None,
) -> GameValidatorAIResult:
    """Use the builder to fix evidenced quality gaps, with Unity as the safety gate."""

    from game_pipeline.codex_cli import CodexGameHarness, CodexHarnessSettings

    builder = os.environ["MAINFLOW_GAME_BUILDER"].strip().lower()
    max_repairs = int(os.environ.get("MAINFLOW_GAME_QUALITY_REPAIRS", "8"))
    if not 0 <= max_repairs <= 10:
        raise ValueError("MAINFLOW_GAME_QUALITY_REPAIRS must be between 0 and 10")
    time_budget = int(os.environ.get("MAINFLOW_GAME_QUALITY_TIME_BUDGET_SECONDS", "2400"))
    if not 60 <= time_budget <= 7200:
        raise ValueError("MAINFLOW_GAME_QUALITY_TIME_BUDGET_SECONDS must be between 60 and 7200")
    if not max_repairs:
        return initial_report
    workspace = manager.ensure_project(project_id)
    project_root = workspace / "game" / "unity_project"
    record = lambda name, data: manager.write_json(
        project_id,
        "validation",
        f"quality_repair/{name}.json",
        data,
        producer="game_quality_validator",
    )
    if builder == "codex_cli":
        harness = CodexGameHarness(
            CodexHarnessSettings.from_environment(),
            audit_root=workspace / "validation" / "codex" / "quality_repair",
            record=record,
        )
        review = run_codex_quality_review
    else:
        from game_pipeline.claude_code import ClaudeCodeGameHarness
        from game_pipeline.claude_code.config import ClaudeCodeHarnessSettings

        harness = ClaudeCodeGameHarness(
            ClaudeCodeHarnessSettings.from_environment(),
            audit_root=workspace / "validation" / "claude_code" / "quality_repair",
            record=record,
        )
        review = run_claude_code_quality_review

    report = initial_report
    previous_repair_error = ""
    previous_finding = ""
    stalled_attempts = 0
    deadline = monotonic() + time_budget
    record("audit_00", report)
    for attempt in range(1, max_repairs + 1):
        if monotonic() >= deadline:
            record("time_budget_exhausted", {"attempt": attempt, "seconds": time_budget})
            break
        actionable = [
            finding
            for finding in report.get("findings", [])
            if finding.get("severity") in {"error", "warning"}
            and finding.get("category")
            in {
                "requirement",
                "gameplay",
                "content",
                "presentation",
                "progression",
                "balance",
                "integration",
                "evidence",
            }
            and "placeholder" not in finding.get("message", "").lower()
            and (
                finding.get("category")
                in {
                    "requirement",
                    "gameplay",
                    "integration",
                    "progression",
                    "content",
                    "presentation",
                }
                or any(
                    "game/unity_project/Assets/" in str(path).replace("\\", "/")
                    or str(path).replace("\\", "/").startswith("Assets/")
                    for path in finding.get("evidence", [])
                )
            )
        ]
        if not actionable:
            break
        # Batch several independent gaps before the costly Unity/review cycle. A single-item
        # turn required eight full CLI sessions for the same persistent findings in practice.
        gameplay_errors = [
            finding
            for finding in actionable
            if finding.get("severity") == "error"
            and finding.get("category") in {"gameplay", "requirement", "integration"}
        ]
        if gameplay_errors:
            # Repair a broken state transition on its own. Mixing it with broad pacing/UI
            # revisions made the Unity regression rollback obscure the original defect.
            actionable = gameplay_errors[:1]
        else:
            actionable = sorted(
                actionable,
                key=lambda finding: finding.get("severity") != "error",
            )[:2]
        current_finding = " | ".join(str(item.get("message", "")) for item in actionable)
        if previous_repair_error:
            actionable.append(
                {
                    "severity": "error",
                    "category": "integration",
                    "message": (
                        "The previous quality patch was rolled back after Unity validation. "
                        "Use a different, compile-safe implementation and first resolve this "
                        f"failure: {previous_repair_error}"
                    ),
                    "evidence": [],
                }
            )
        log(f"독립 품질 평가의 기능 누락을 CLI Agent가 수정합니다 ({attempt}/{max_repairs}).")
        try:
            source_before = _project_source_signature(project_root)
            outcome = harness.repair_quality_findings(
                project_root=project_root,
                draft=evidence["game_logic_draft"],
                request=evidence["parsed_request"],
                findings=actionable,
                iteration=attempt,
            )
            evidence["post_quality_unity_validation"] = {
                "status": outcome.status,
                "checks": outcome.checks,
                "issues": outcome.issues,
                "unity_log": outcome.unity_log[-12000:],
            }
            record(f"unity_validation_{attempt:02d}", evidence["post_quality_unity_validation"])
            if state is not None and evidence.get("visual_validation_result", {}).get(
                "ui_readability"
            ):
                from mainflow.nodes.visual_validation import _audit_applied_ui

                refreshed_ui = _audit_applied_ui(
                    manager, state, artifact_suffix=f"_quality_{attempt:02d}"
                )
                if refreshed_ui is not None:
                    evidence["visual_validation_result"] = {
                        **evidence["visual_validation_result"],
                        "ui_readability": refreshed_ui,
                    }
            reviewed = review(project_root=workspace, project_id=project_id, evidence=evidence)
            report = _normalize_placeholder_visual_limitation(
                cast(GameValidatorAIResult, reviewed),
                evidence.get("final_validation_result", {"status": "passed"}),
                evidence.get("visual_validation_result"),
            )
            report = _normalize_duration_limitation(
                report,
                evidence.get("final_validation_result", {"status": "passed"}),
            )
            record(f"audit_{attempt:02d}", report)
            if report.get("status") == "passed":
                return report
            source_after = _project_source_signature(project_root)
            if current_finding == previous_finding and source_after == source_before:
                stalled_attempts += 1
            else:
                stalled_attempts = 0
            previous_finding = current_finding
            previous_repair_error = ""
            if stalled_attempts >= 2:
                record(
                    "stalled",
                    {"attempt": attempt, "finding": current_finding, "reason": "source unchanged"},
                )
                break
        except Exception as error:  # noqa: BLE001 - preserve the original audit and project
            previous_repair_error = f"{type(error).__name__}: {error}"
            record(f"repair_error_{attempt:02d}", {"error": previous_repair_error})
            if isinstance(error, OSError):
                # A host filesystem/process failure is not a gameplay patch failure. Repeating
                # the same CLI request cannot fix it, so surface it at the workflow boundary.
                raise
            report = cast(
                GameValidatorAIResult,
                {
                    **report,
                    "limitations": [
                        *report.get("limitations", []),
                        f"Quality repair {attempt} could not pass Unity: {previous_repair_error}",
                    ],
                },
            )
            continue
    return report


def _project_source_signature(project_root: Path) -> tuple[tuple[str, int, int], ...]:
    """Detect a repair turn that repeatedly makes no gameplay or scene changes."""

    assets = project_root / "Assets"
    if not assets.exists():
        return ()
    result = []
    for path in assets.rglob("*"):
        if path.suffix.lower() not in {".cs", ".unity", ".prefab", ".asset"} or not path.is_file():
            continue
        stat = path.stat()
        result.append((path.relative_to(project_root).as_posix(), stat.st_size, stat.st_mtime_ns))
    return tuple(sorted(result))


def _normalize_placeholder_visual_limitation(
    report: GameValidatorAIResult,
    final_result: dict[str, Any],
    visual_result: dict[str, Any] | None = None,
) -> GameValidatorAIResult:
    """Keep an intentionally skipped VLM comparison from failing quality review alone."""

    if final_result.get("status") != "passed":
        return report

    visual_disabled = (
        isinstance(visual_result, dict)
        and visual_result.get("mode") == "disabled"
        and visual_result.get("status") == "skipped"
    )

    def is_placeholder_visual(item: dict[str, Any]) -> bool:
        text = " ".join(
            [
                str(item.get("category", "")),
                str(item.get("message", "")),
                str(item.get("requirement", "")),
                *(str(value) for value in item.get("evidence", [])),
            ]
        ).lower()
        placeholder_skip = (
            "visual" in text
            and "placeholder" in text
            and any(marker in text for marker in ("skip", "disabled", "suppressed"))
        )
        disabled_vlm_skip = (
            visual_disabled
            and any(marker in text for marker in ("visual validation", "vlm", "시각 검증"))
            and any(marker in text for marker in ("skip", "disabled", "not run", "생략", "비활성"))
            and not any(marker in text for marker in ("unreadable", "overlap", "가독성", "겹침"))
        )
        return placeholder_skip or disabled_vlm_skip

    findings: list[dict[str, Any]] = []
    for finding in report.get("findings", []):
        if is_placeholder_visual(finding) and finding.get("severity") in {"error", "warning"}:
            findings.append({**finding, "severity": "info"})
        else:
            findings.append(finding)

    unresolved_findings = [
        finding for finding in findings if finding.get("severity") in {"error", "warning"}
    ]
    unresolved_coverage = [
        item
        for item in report.get("requirement_coverage", [])
        if item.get("status") != "satisfied" and not is_placeholder_visual(item)
    ]
    status = report.get("status")
    if status == "needs_revision" and not unresolved_findings and not unresolved_coverage:
        status = "passed"

    return cast(GameValidatorAIResult, {**report, "status": status, "findings": findings})


def _is_normal_play_duration_assessment(item: dict[str, Any]) -> bool:
    """Identify estimated whole-game length, not timer or countdown functionality."""

    subject = " ".join(
        str(item.get(key, "")) for key in ("requirement", "message", "recommendation")
    ).casefold()
    evidence = " ".join(str(value) for value in item.get("evidence", [])).casefold()
    explicit_duration = any(
        marker in subject
        for marker in (
            "normal-play duration",
            "normal play duration",
            "normal playtime",
            "normal-play time",
            "playtime target",
            "전체 플레이 시간",
            "최소 플레이 시간",
            "목표 플레이 시간",
            "목표 플레이타임",
            "게임 분량",
            "분량",
        )
    )
    contract_estimate = any(
        marker in evidence
        for marker in (
            "pacing_contract.json",
            "minimum_normal_play_seconds",
            "target_duration_seconds",
        )
    ) and any(marker in subject for marker in ("pacing", "duration", "playtime", "분량"))
    return explicit_duration or contract_estimate


def _normalize_duration_limitation(
    report: GameValidatorAIResult,
    final_result: dict[str, Any],
) -> GameValidatorAIResult:
    """Keep estimated play length visible without making it a release gate."""

    if final_result.get("status") != "passed":
        return report

    duration_downgraded = any(
        _is_normal_play_duration_assessment(finding)
        and finding.get("severity") in {"error", "warning"}
        for finding in report.get("findings", [])
    )
    findings = [
        {**finding, "severity": "info"} if _is_normal_play_duration_assessment(finding) else finding
        for finding in report.get("findings", [])
    ]
    coverage = [
        {**item, "status": "unverifiable"}
        if _is_normal_play_duration_assessment(item) and item.get("status") != "satisfied"
        else item
        for item in report.get("requirement_coverage", [])
    ]
    blocking_findings = any(finding.get("severity") in {"error", "warning"} for finding in findings)
    blocking_coverage = any(
        item.get("status") in {"partial", "missing", "unverifiable"}
        and not _is_normal_play_duration_assessment(item)
        for item in coverage
    )
    status = report.get("status")
    if status == "passed" and any(finding.get("severity") == "error" for finding in findings):
        status = "needs_revision"
    if (
        status in {"needs_revision", "failed"}
        and not blocking_findings
        and not blocking_coverage
        and (status == "needs_revision" or duration_downgraded)
    ):
        status = "passed"

    return cast(
        GameValidatorAIResult,
        {
            **report,
            "status": status,
            "findings": findings,
            "requirement_coverage": coverage,
            "summary": (
                "Independent review passed; estimated normal play duration remains informational."
                if status == "passed" and report.get("status") in {"needs_revision", "failed"}
                else report.get("summary", "")
            ),
        },
    )


def _hard_failure_report(evidence: dict[str, Any]) -> GameValidatorAIResult:
    failed = [
        name
        for name, payload in evidence.items()
        if name.endswith("validation_result")
        and isinstance(payload, dict)
        and payload.get("status") not in {"passed", "skipped"}
    ]
    return {
        "report_version": "1.0.0",
        "contract_version": CONTRACT_VERSION,
        "status": "failed",
        "score": 0.0,
        "summary": "Hard validation failed, so the completed game is not eligible for AI approval.",
        "requirement_coverage": [
            {
                "requirement": "All deterministic and Unity validation gates must pass",
                "status": "missing",
                "evidence": failed or ["final_validation_result.status"],
            }
        ],
        "findings": [
            {
                "severity": "error",
                "category": "evidence",
                "message": "One or more mandatory validation stages failed.",
                "evidence": failed or ["final_validation_result.status"],
                "recommendation": "Resolve hard validation errors before requesting an AI quality audit.",
            }
        ],
        "strengths": [],
        "limitations": ["AI quality review was not run because hard validation failed."],
        "inspected_files": [],
        "provider": "none",
        "model": "none",
        "attempts": 0,
        "turns": 0,
        "tool_calls": [],
    }


def _disabled_report() -> GameValidatorAIResult:
    return {
        "report_version": "1.0.0",
        "contract_version": CONTRACT_VERSION,
        "status": "needs_revision",
        "score": 0.0,
        "summary": "Independent Game Validator AI is disabled by configuration.",
        "requirement_coverage": [
            {
                "requirement": "Independent AI quality evaluation",
                "status": "unverifiable",
                "evidence": ["MAINFLOW_GAME_VALIDATOR_ENABLED=false"],
            }
        ],
        "findings": [],
        "strengths": [],
        "limitations": ["No AI quality judgment was produced."],
        "inspected_files": [],
        "provider": "none",
        "model": "none",
        "attempts": 0,
        "turns": 0,
        "tool_calls": [],
    }


def _execution_failure_report(error: Exception) -> GameValidatorAIResult:
    diagnostic = f"{type(error).__name__}: {error}"
    return {
        "report_version": "1.0.0",
        "contract_version": CONTRACT_VERSION,
        "status": "failed",
        "score": 0.0,
        "summary": f"독립 품질 검증 중 예외가 발생했습니다: {diagnostic}",
        "requirement_coverage": [
            {
                "requirement": "Independent AI quality evaluation",
                "status": "unverifiable",
                "evidence": [diagnostic],
            }
        ],
        "findings": [
            {
                "severity": "error",
                "category": "evidence",
                "message": f"Validator execution failed: {diagnostic}",
                "evidence": ["game_quality_validator execution"],
                "recommendation": (
                    "Inspect validation/game_quality_validator_error.json for the failing "
                    "operation and traceback."
                ),
            }
        ],
        "strengths": [],
        "limitations": ["The independent quality review or repair could not complete."],
        "inspected_files": [],
        "provider": "none",
        "model": "none",
        "attempts": 0,
        "turns": 0,
        "tool_calls": [],
    }
