"""Whole-project implementation and deterministic Unity repair loop using Codex CLI."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game_pipeline.codex_cli.config import CodexHarnessSettings
from game_pipeline.codex_cli.preflight import CodexPreflightResult, run_codex_preflight
from game_pipeline.codex_cli.runner import CodexCliResult, CodexCliRunner
from game_pipeline.game_failure_classifier import classify_failure
from game_pipeline.unity_project_validator import UnityProjectValidator, UnityValidationOutcome
from mainflow.contracts import CONTRACT_VERSION, GameLogicDesign, GameLogicDraft, ParsedRequest

Recorder = Callable[[str, Any], None]


COMPLETION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["completed", "needs_attention"]},
        "summary": {"type": "string"},
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "implemented_features": {"type": "array", "items": {"type": "string"}},
        "tests_run": {"type": "array", "items": {"type": "string"}},
        "unresolved_requirements": {"type": "array", "items": {"type": "string"}},
        "recommended_validation": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "status",
        "summary",
        "changed_files",
        "implemented_features",
        "tests_run",
        "unresolved_requirements",
        "recommended_validation",
    ],
    "additionalProperties": False,
}

QUALITY_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["passed", "needs_revision", "failed"]},
        "score": {"type": "number", "minimum": 0, "maximum": 100},
        "summary": {"type": "string"},
        "requirement_coverage": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["satisfied", "partial", "missing", "unverifiable"],
                    },
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["requirement", "status", "evidence"],
                "additionalProperties": False,
            },
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["error", "warning", "info"]},
                    "category": {
                        "type": "string",
                        "enum": [
                            "requirement",
                            "gameplay",
                            "progression",
                            "balance",
                            "content",
                            "presentation",
                            "integration",
                            "evidence",
                        ],
                    },
                    "message": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "recommendation": {"type": "string"},
                },
                "required": [
                    "severity",
                    "category",
                    "message",
                    "evidence",
                    "recommendation",
                ],
                "additionalProperties": False,
            },
        },
        "strengths": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "inspected_files": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "status",
        "score",
        "summary",
        "requirement_coverage",
        "findings",
        "strengths",
        "limitations",
        "inspected_files",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class CodexHarnessResult:
    preflight: CodexPreflightResult
    implementation: CodexCliResult
    repair_results: tuple[CodexCliResult, ...]
    validation_attempts: tuple[dict[str, Any], ...]
    provider: str = "codex_cli"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "preflight": self.preflight.to_dict(),
            "implementation": self.implementation.final_response,
            "repair_results": [result.final_response for result in self.repair_results],
            "validation_attempts": list(self.validation_attempts),
        }


@dataclass(frozen=True)
class AgentPostValidationRepairResult:
    preflight: CodexPreflightResult
    outcome: UnityValidationOutcome
    repair_results: tuple[CodexCliResult, ...]
    validation_attempts: tuple[dict[str, Any], ...]
    provider: str
    phase: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "phase": self.phase,
            "preflight": self.preflight.to_dict(),
            "status": self.outcome.status,
            "repair_results": [result.final_response for result in self.repair_results],
            "validation_attempts": list(self.validation_attempts),
        }


@dataclass(frozen=True)
class _ProjectSourceSnapshot:
    files: dict[str, bytes]

    @classmethod
    def capture(cls, project_root: Path) -> _ProjectSourceSnapshot:
        files: dict[str, bytes] = {}
        for directory in ("Assets", "Packages", "ProjectSettings"):
            root = project_root / directory
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file():
                    files[path.relative_to(project_root).as_posix()] = path.read_bytes()
        return cls(files)

    def restore(self, project_root: Path) -> None:
        expected = set(self.files)
        for directory in ("Assets", "Packages", "ProjectSettings"):
            root = project_root / directory
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.relative_to(project_root).as_posix() not in expected:
                    path.unlink()
        for relative, content in self.files.items():
            target = project_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)


_PROTECTED_ASSET_PREFIX = "Assets/GameTemplate/Generated/AppliedAssets/"
_PROTECTED_ASSET_FILES = {
    "Assets/GameTemplate/Generated/AssetBindingManifest.json",
    "Assets/GameTemplate/Generated/AssetBindingReport.json",
}


def _restore_protected_asset_files(
    snapshot: _ProjectSourceSnapshot, project_root: Path
) -> list[str]:
    """Undo downstream-agent edits to validated media while retaining gameplay source repairs."""

    protected = {
        relative: content
        for relative, content in snapshot.files.items()
        if relative.startswith(_PROTECTED_ASSET_PREFIX) or relative in _PROTECTED_ASSET_FILES
    }
    changed: list[str] = []
    applied_root = project_root / _PROTECTED_ASSET_PREFIX
    if applied_root.is_dir():
        for path in applied_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(project_root).as_posix()
            if relative not in protected:
                path.unlink()
                changed.append(relative)
    for relative, content in protected.items():
        target = project_root / relative
        if not target.is_file() or target.read_bytes() != content:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            changed.append(relative)
    return sorted(set(changed))


class CodexGameHarness:
    def __init__(
        self,
        settings: CodexHarnessSettings,
        *,
        audit_root: Path,
        record: Recorder | None = None,
        runner: Any | None = None,
        preflight_runner: Callable[[Any], CodexPreflightResult] = run_codex_preflight,
        provider: str = "codex_cli",
        agent_label: str = "Codex",
        instruction_filename: str = "AGENTS.md",
        total_timeout_environment: str = "MAINFLOW_CODEX_TOTAL_TIMEOUT_SECONDS",
    ) -> None:
        self.settings = settings
        self.audit_root = audit_root.resolve()
        self.record = record
        self.runner = runner or CodexCliRunner(settings)
        self.preflight_runner = preflight_runner
        self.provider = provider
        self.agent_label = agent_label
        self.instruction_filename = instruction_filename
        self.total_timeout_environment = total_timeout_environment
        self.preflight: CodexPreflightResult | None = None
        self.implementation: CodexCliResult | None = None

    def implement_project(
        self,
        *,
        project_root: Path,
        design: GameLogicDesign,
        request: ParsedRequest,
    ) -> CodexCliResult:
        self.preflight = self.preflight_runner(self.settings)
        self._record(f"{self.provider}_preflight", self.preflight.to_dict())
        _prepare_host_owned_source_roots(project_root)
        initial_permissions = _normalize_windows_project_permissions(project_root)
        self._record(
            f"{self.provider}_project_permissions_before_implementation", initial_permissions
        )
        _require_normalized_permissions(
            initial_permissions, f"before {self.agent_label} implementation"
        )
        _write_project_instructions(
            project_root,
            design,
            request,
            agent_label=self.agent_label,
            filename=self.instruction_filename,
        )
        prompt = _implementation_prompt(
            design, request, instruction_filename=self.instruction_filename
        )
        self.implementation = self.runner.run(
            project_root=project_root,
            prompt=prompt,
            schema=COMPLETION_SCHEMA,
            audit_directory=self.audit_root / "implementation",
        )
        _require_agent_completion(self.implementation, "initial implementation")
        permission_report = _normalize_windows_project_permissions(project_root)
        self._record(f"{self.provider}_project_permissions_after_implementation", permission_report)
        _require_normalized_permissions(
            permission_report, f"after {self.agent_label} implementation"
        )
        self._record(f"{self.provider}_implementation", self.implementation.final_response)
        return self.implementation

    def validate_and_repair(
        self,
        *,
        project_root: Path,
        design: GameLogicDesign,
        request: ParsedRequest,
    ) -> CodexHarnessResult:
        if self.preflight is None or self.implementation is None:
            raise RuntimeError(f"{self.agent_label} implementation must run before validation")
        outcome, repairs, attempts = self._run_validation_repair_loop(
            project_root=project_root,
            draft=_validation_draft(project_root, design),
            request=request,
            phase="design_game_logic",
        )
        if outcome.status != "passed":
            raise RuntimeError(f"{self.agent_label} validation repair loop ended without success")
        return CodexHarnessResult(
            self.preflight,
            self.implementation,
            repairs,
            attempts,
            self.provider,
        )

    def repair_existing_project(
        self,
        *,
        project_root: Path,
        draft: GameLogicDraft,
        request: ParsedRequest,
        initial_outcome: UnityValidationOutcome,
        phase: str,
        max_repairs: int,
    ) -> AgentPostValidationRepairResult:
        """Repair a project that failed in a downstream authoritative validation stage."""

        if max_repairs < 1:
            raise ValueError("Post-validation repair count must be positive")
        if self.preflight is None:
            self.preflight = self.preflight_runner(self.settings)
            self._record(f"{self.provider}_{phase}_preflight", self.preflight.to_dict())
        _prepare_host_owned_source_roots(project_root)
        permissions = _normalize_windows_project_permissions(project_root)
        self._record(f"{self.provider}_{phase}_project_permissions", permissions)
        _require_normalized_permissions(permissions, f"before downstream {phase} repair")
        outcome, repairs, attempts = self._run_validation_repair_loop(
            project_root=project_root,
            draft=draft,
            request=request,
            phase=phase,
            initial_outcome=initial_outcome,
            max_repairs=max_repairs,
        )
        return AgentPostValidationRepairResult(
            self.preflight,
            outcome,
            repairs,
            attempts,
            self.provider,
            phase,
        )

    def repair_quality_findings(
        self,
        *,
        project_root: Path,
        draft: GameLogicDraft,
        request: ParsedRequest,
        findings: list[dict[str, Any]],
        iteration: int,
    ) -> UnityValidationOutcome:
        """Repair an independently audited gap, then require Unity to still pass."""

        if self.preflight is None:
            self.preflight = self.preflight_runner(self.settings)
        _prepare_host_owned_source_roots(project_root)
        permissions = _normalize_windows_project_permissions(project_root)
        _require_normalized_permissions(permissions, "before quality repair")
        snapshot = _ProjectSourceSnapshot.capture(project_root)
        prompt = f"""Repair the independently audited Unity gameplay and presentation gaps.

Iteration: {iteration}
User request: {request["condition"]}
Audited findings with source evidence:
{json.dumps(findings[:12], ensure_ascii=False, indent=2)}

Read each cited source file and implement the missing behavior. Preserve existing working
features, asset bytes, asset manifests, module identities, and user requirements. Do not
weaken validators or mark a feature complete without executable evidence. Do not edit
design or validation JSON to conceal a missing implementation. Do not run Unity; the host
will compile and execute Play Mode after your edits. Add focused Unity Test Framework
PlayMode regression tests tagged `FeatureChecklist` for each repaired gameplay behavior;
assert observable state transitions rather than checking that a class or method exists.
For upgrade UI findings, show explicit current-to-projected values using the same formula as the
purchase operation, then refresh the panel after purchase. For audio integration findings, read
`Assets/GameTemplate/Generated/AssetRequests/sound_asset_request.json`, preserve every
`generation_spec.audio_cue`, and raise the exact cue at the successful gameplay transition. Do not
invent an alternate cue ID or treat scene-bound audio as proof that the event is wired.
Before adding a cross-file type reference, read the referenced class and its namespace and
either import that namespace or use the fully-qualified type name. Put every new public Unity
component in a filename-matched source file so Unity can serialize it. Treat authored normal
gameplay duration separately from accelerated smoke-test time: preserve the requested runtime
pacing while exposing deterministic state transitions that the host can test quickly.
Return the required structured report.
"""
        try:
            result = self.runner.run(
                project_root=project_root,
                prompt=prompt,
                schema=COMPLETION_SCHEMA,
                audit_directory=self.audit_root / "quality_repair" / f"attempt_{iteration:02d}",
            )
            _require_agent_completion(result, f"quality repair {iteration}")
            self._record(f"{self.provider}_quality_repair_{iteration}", result.final_response)
            restored = _restore_protected_asset_files(snapshot, project_root)
            self._record(f"{self.provider}_quality_protected_assets_{iteration}", restored)
            permissions = _normalize_windows_project_permissions(project_root)
            _require_normalized_permissions(permissions, "after quality repair")
            validator = UnityProjectValidator(
                mode="required",
                unity_editor=os.environ.get("UNITY_EDITOR_PATH"),
                timeout_seconds=int(
                    os.environ.get("MAINFLOW_UNITY_VALIDATION_TIMEOUT_SECONDS", "300")
                ),
            )
            outcome = validator.validate(project_root, draft, request)
            self._record(
                f"{self.provider}_quality_unity_validation_{iteration}",
                {"status": outcome.status, "checks": outcome.checks, "issues": outcome.issues},
            )
            if outcome.status != "passed":
                try:
                    unity_repairs = int(os.environ.get("MAINFLOW_GAME_QUALITY_UNITY_REPAIRS", "2"))
                except ValueError as error:
                    raise ValueError(
                        "MAINFLOW_GAME_QUALITY_UNITY_REPAIRS must be an integer"
                    ) from error
                if not 0 <= unity_repairs <= 3:
                    raise ValueError("MAINFLOW_GAME_QUALITY_UNITY_REPAIRS must be between 0 and 3")
                outcome, _, _ = self._run_validation_repair_loop(
                    project_root=project_root,
                    draft=draft,
                    request=request,
                    phase=f"quality_repair_{iteration}",
                    initial_outcome=outcome,
                    max_repairs=unity_repairs,
                )
            if os.environ.get("MAINFLOW_FEATURE_CHECKLIST_VALIDATION", "1") == "1":
                from game_pipeline.dynamic_feature_checklist import load_generated_checklist
                from game_pipeline.feature_checklist_validation import FeatureChecklistWorkflow

                workspace_root = project_root.parent.parent
                if (workspace_root / "validation" / "feature_checklists").is_dir():
                    editor = validator.unity_editor or validator.find_unity_editor(
                        validator._read_project_version(project_root)
                    )
                    if editor is None:
                        raise RuntimeError("Unity Editor is required to rerun feature checklists")
                    workflow = FeatureChecklistWorkflow(
                        unity_editor=editor,
                        timeout_seconds=int(
                            os.environ.get("MAINFLOW_UNITY_VALIDATION_TIMEOUT_SECONDS", "300")
                        ),
                        max_retries=0,
                    )
                    checklist = load_generated_checklist(workspace_root)
                    results, checklist_log = workflow._run_tests(project_root, checklist)
                    self._record(
                        f"{self.provider}_quality_feature_checklists_{iteration}",
                        {
                            "results": [item.__dict__ for item in results],
                            "log": checklist_log[-12000:],
                        },
                    )
                    failed = [item for item in results if item.status in {"failed", "error"}]
                    if failed:
                        raise RuntimeError(
                            "Quality repair failed feature checklists: "
                            + "; ".join(
                                f"{item.feature_name}: {item.message}" for item in failed[:6]
                            )
                        )
                    outcome.checks.append(
                        {
                            "criterion_id": "quality.feature_checklists",
                            "passed": True,
                            "message": f"{len(results)} feature checklist tests passed after quality repair",
                        }
                    )
            return outcome
        except Exception:
            snapshot.restore(project_root)
            _normalize_windows_project_permissions(project_root)
            raise

    def _run_validation_repair_loop(
        self,
        *,
        project_root: Path,
        draft: GameLogicDraft,
        request: ParsedRequest,
        phase: str,
        initial_outcome: UnityValidationOutcome | None = None,
        max_repairs: int | None = None,
    ) -> tuple[
        UnityValidationOutcome,
        tuple[CodexCliResult, ...],
        tuple[dict[str, Any], ...],
    ]:
        validator = UnityProjectValidator(
            mode=os.environ.get("MAINFLOW_UNITY_VALIDATION_MODE", "required"),
            unity_editor=os.environ.get("UNITY_EDITOR_PATH"),
            timeout_seconds=int(os.environ.get("MAINFLOW_UNITY_VALIDATION_TIMEOUT_SECONDS", "300")),
        )
        started = time.monotonic()
        attempts: list[dict[str, Any]] = []
        repairs: list[CodexCliResult] = []
        signatures: dict[str, int] = {}
        pending_snapshot: _ProjectSourceSnapshot | None = None
        pending_baseline_outcome: UnityValidationOutcome | None = None
        pending_baseline_evidence: dict[str, Any] | None = None
        pending_baseline_severity: int | None = None
        repair_limit = self.settings.max_repairs if max_repairs is None else max_repairs
        for attempt in range(repair_limit + 1):
            outcome = (
                initial_outcome
                if attempt == 0 and initial_outcome is not None
                else validator.validate(project_root, draft, request)
            )
            evidence = {
                "attempt": attempt,
                "phase": phase,
                "status": outcome.status,
                "checks": outcome.checks,
                "issues": outcome.issues,
                "unity_log": outcome.unity_log,
            }
            attempts.append(evidence)
            self._record(f"{self.provider}_{phase}_validation_attempt_{attempt}", evidence)
            raw_classification = classify_failure(outcome)
            if raw_classification["target"] == "infrastructure":
                raise RuntimeError(
                    "Unity validation could not start because of a host infrastructure "
                    f"problem; {self.agent_label} source repair was skipped: "
                    f"{outcome.issues}"
                )
            regression_evidence: dict[str, Any] | None = None
            if (
                pending_snapshot is not None
                and pending_baseline_outcome is not None
                and pending_baseline_evidence is not None
                and pending_baseline_severity is not None
                and _repair_is_regression(
                    pending_baseline_outcome,
                    outcome,
                    pending_baseline_severity,
                )
            ):
                regression_evidence = evidence
                pending_snapshot.restore(project_root)
                permission_report = _normalize_windows_project_permissions(project_root)
                self._record(
                    f"{self.provider}_{phase}_repair_rollback_{attempt}",
                    {
                        "reason": "repair introduced a more severe Unity failure",
                        "baseline": _bounded_feedback(pending_baseline_evidence),
                        "regression": _bounded_feedback(regression_evidence),
                        "permissions": permission_report,
                    },
                )
                _require_normalized_permissions(permission_report, "after repair rollback")
                outcome = pending_baseline_outcome
                evidence = {
                    **pending_baseline_evidence,
                    "attempt": attempt,
                    "rolled_back_regression": _bounded_feedback(regression_evidence),
                }
            pending_snapshot = None
            pending_baseline_outcome = None
            pending_baseline_evidence = None
            pending_baseline_severity = None
            if outcome.status == "passed":
                return outcome, tuple(repairs), tuple(attempts)
            signature = _failure_signature(outcome)
            signatures[signature] = signatures.get(signature, 0) + 1
            if attempt >= repair_limit:
                raise RuntimeError(
                    f"{self.agent_label} Unity validation failed after {attempt} repairs: "
                    f"{outcome.issues}; "
                    f"diagnostics={_signature_diagnostics(outcome.unity_log)}"
                )
            if signatures[signature] >= 3:
                raise RuntimeError(
                    f"{self.agent_label} repair stopped because the same Unity failure repeated "
                    "three times: "
                    f"{outcome.issues}; diagnostics={_signature_diagnostics(outcome.unity_log)}"
                )
            if time.monotonic() - started >= self.settings.total_timeout_seconds:
                raise TimeoutError(f"{self.total_timeout_environment} was exhausted")
            feedback = _bounded_feedback(evidence)
            if regression_evidence is not None:
                feedback["rolled_back_regression"] = _bounded_feedback(regression_evidence)
                feedback["repair_constraint"] = (
                    "The previous repair was rolled back because it introduced a more severe "
                    "failure. Preserve the restored module identities, source files, and scene "
                    "bindings while fixing the original failure by a different approach."
                )
            pending_snapshot = _ProjectSourceSnapshot.capture(project_root)
            pending_baseline_outcome = outcome
            pending_baseline_evidence = evidence
            pending_baseline_severity = _failure_severity(outcome)
            diagnostic_summary = _signature_diagnostics(outcome.unity_log)
            failure_summary = (
                diagnostic_summary[0]
                if diagnostic_summary
                else outcome.issues[0]
                if outcome.issues
                else "unknown Unity validation failure"
            )
            print(
                f"[AGENT][repair] Unity 검증 오류 수정 {attempt + 1}/{repair_limit}: "
                f"{failure_summary}",
                flush=True,
            )
            try:
                repair = self.runner.run(
                    project_root=project_root,
                    prompt=_repair_prompt(feedback, attempt + 1, phase=phase),
                    schema=COMPLETION_SCHEMA,
                    audit_directory=self.audit_root / phase / f"repair_{attempt + 1:02d}",
                )
                _require_agent_completion(repair, f"{phase} repair {attempt + 1}")
            except Exception:
                pending_snapshot.restore(project_root)
                _normalize_windows_project_permissions(project_root)
                raise
            protected_restorations: list[str] = []
            if phase == "final_validation":
                protected_restorations = _restore_protected_asset_files(
                    pending_snapshot, project_root
                )
                if protected_restorations:
                    self._record(
                        f"{self.provider}_{phase}_protected_assets_restored_{attempt + 1}",
                        {
                            "reason": (
                                "The CLI agent may repair gameplay and bindings but may not "
                                "replace already validated generated assets or their manifests."
                            ),
                            "paths": protected_restorations,
                        },
                    )
            permission_report = _normalize_windows_project_permissions(project_root)
            repairs.append(repair)
            self._record(f"{self.provider}_{phase}_repair_{attempt + 1}", repair.final_response)
            self._record(
                f"{self.provider}_{phase}_repair_permissions_{attempt + 1}", permission_report
            )
            _require_normalized_permissions(
                permission_report, f"after {self.agent_label} repair {attempt + 1}"
            )
        raise AssertionError("unreachable")

    def _record(self, name: str, value: Any) -> None:
        if self.record is not None:
            self.record(name, value)


def _require_agent_completion(result: CodexCliResult, phase: str) -> None:
    """Stop immediately when the CLI reports that it could not inspect or edit the project."""

    response = result.final_response
    if response.get("status") == "completed":
        return
    summary = str(response.get("summary", "Agent could not complete the requested work"))
    unresolved = response.get("unresolved_requirements", [])
    detail = "; ".join(str(item) for item in unresolved[:5]) if isinstance(unresolved, list) else ""
    suffix = f" Unresolved: {detail}" if detail else ""
    raise RuntimeError(f"AGENT_IMPLEMENTATION_INCOMPLETE ({phase}): {summary}.{suffix}")


def prepare_design_for_codex(design: GameLogicDesign) -> GameLogicDesign:
    """Give a CLI agent ownership of gameplay while retaining the validated scaffold.

    The previous harness only received mechanics missing from the reusable catalog.  That made
    the agent treat every catalog hit as finished and reproduced the same genre prototype for
    different requests.  Common modules remain infrastructure, but every genre/gameplay module
    and every unsupported mechanic now requires a request-specific agent audit or rewrite.
    """

    common_modules = set(design.get("common_modules", []))
    template_gameplay_modules = [
        module_id
        for module_id in design.get("selected_modules", [])
        if module_id not in common_modules
    ]
    requirements = list(
        dict.fromkeys([*template_gameplay_modules, *design["unsupported_mechanics"]])
    )
    design["agent_harness_mode"] = "whole_project"
    design["agent_harness_template_modules"] = template_gameplay_modules
    design["agent_harness_feature_requirements"] = deepcopy(
        design.get("game_spec", {}).get("features", [])
    )
    design["codex_harness_requirements"] = requirements
    design["unsupported_mechanics"] = []
    design["generated_modules"] = []
    return design


prepare_design_for_agent_harness = prepare_design_for_codex


def run_codex_quality_review(
    *,
    project_root: Path,
    project_id: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Run the independent final audit without exposing provider API keys."""

    settings = CodexHarnessSettings.from_environment()
    preflight = run_codex_preflight(settings)
    audit_root = project_root / "validation" / "codex" / "final_quality_review"
    prompt = f"""Independently audit the completed Unity game for project {project_id}.

This is a read-only quality review. Do not edit any file. Read
`game/project_context_index.json`, the generated design documents, relevant Unity runtime scripts,
and validation records. Check requirement coverage, connected gameplay, progression, content,
balance, presentation, and asset integration. Hard validator failures cannot be overruled. Cite
project-relative paths or hard check IDs for every nontrivial conclusion.
If the image backend deliberately produced placeholders and visual validation is marked skipped,
record that only as an info-level limitation; do not emit a warning/error or fail the game solely
because no real image asset was applied. Judge primitive fallback readability separately.
Check actual gameplay behavior independently of the hard smoke-test status. If post-quality
Unity validation evidence exists, prefer it over the earlier pre-repair run.

HOST EVIDENCE:
{json.dumps(evidence, ensure_ascii=False, indent=2)}
"""
    result = CodexCliRunner(settings).run(
        project_root=project_root,
        prompt=prompt,
        schema=QUALITY_REVIEW_SCHEMA,
        audit_directory=audit_root,
        sandbox="read-only",
    )
    return {
        "report_version": "1.0.0",
        "contract_version": CONTRACT_VERSION,
        **result.final_response,
        "provider": "codex_cli",
        "model": settings.model or "user-default",
        "attempts": 1,
        "turns": sum(1 for event in result.events if event.get("type") == "turn.completed"),
        "tool_calls": [
            str(event.get("item", {}).get("type"))
            for event in result.events
            if isinstance(event.get("item"), dict)
        ],
        "codex_preflight": preflight.to_dict(),
    }


def _write_project_instructions(
    project_root: Path,
    design: GameLogicDesign,
    request: ParsedRequest,
    *,
    agent_label: str = "Codex",
    filename: str = "AGENTS.md",
) -> None:
    requirements = design.get("codex_harness_requirements", [])
    feature_requirements = design.get("agent_harness_feature_requirements", [])
    template_modules = design.get("agent_harness_template_modules", [])
    text = f"""# Generated Unity project agent instructions

## Goal

Implement a playable Unity 2D vertical slice for this exact request:

{request["condition"]}

- Genre: {request["genre"]}
- Viewpoint: {request["viewpoint"]}
- Gameplay modules and mechanics assigned to {agent_label}: {json.dumps(requirements, ensure_ascii=False)}
- User and inferred feature requirements: {json.dumps(feature_requirements, ensure_ascii=False)}
- Copied gameplay modules requiring request-specific audit: {json.dumps(template_modules, ensure_ascii=False)}

## Harness ownership policy

- The copied Unity project is a compatibility scaffold, not a finished genre template.
- Core bootstrap, validation, asset binding, input abstraction, and project settings may be reused.
- Existing genre gameplay modules, prototype actors, scene-controller behavior, coordinates, content
  counts, UI layout, and tuning are reference implementations only. Their presence does not mean a
  requested feature is implemented.
- Inspect every feature requirement and either substantially adapt the relevant copied gameplay
  implementation or replace it with request-specific code. Do not report completion merely because
  a selected module already compiles.
- Derive the connected core loop, world layout, content placement, progression, camera behavior,
  HUD, win/loss flow, and feedback from the exact user request. Avoid fixed sample coordinates and
  fixed genre-demo sequences when they are not justified by that request.
- Design JSON contains validated requirements and minimum acceptance evidence. Treat generic preset
  content as a lower-bound scaffold, not as an instruction to reproduce the stock prototype.

## Required context

Read every file below before editing code:

- `Assets/GameTemplate/Generated/GameLogicDesign.json`
- `Assets/GameTemplate/Generated/GameBlueprint.json`
- every JSON file in `Assets/GameTemplate/Generated/Design/`
- `Assets/GameTemplate/Generated/AssetRequests/image_asset_request.json`
- `Assets/GameTemplate/Generated/AssetRequests/sound_asset_request.json`
- `Assets/GameTemplate/Generated/GenerationRequest.json`
- `Assets/GameTemplate/Runtime/Core/IGeneratedFeatureModule.cs`
- existing runtime and editor scripts under `Assets/GameTemplate/`

## Boundaries

- Work only inside this Unity project.
- Do not change generated design JSON, `GenerationManifest.json`, package identity, or tests to hide failures.
- Do not commit, push, install unrelated software, or access credentials.
- Prefer project APIs already present. Inspect definitions before referencing a class, member, tag, layer, or package.
- You may refactor copied runtime gameplay modules, prototype controllers, and copied editor-side
  assembly code when necessary for a request-specific game. Preserve the host validation entry
  points, immutable generated contracts, asset binding keys, tests, and project/package identity.
- Implement behavior in source files and connect it to actual scene objects, UI, progression, win/loss flow, and feedback.
- Treat `presentation_plan.json` as an implementation contract, not mood-board text. Build a
  coherent Unity uGUI hierarchy for every specified HUD region and state screen, with anchored
  layout, `CanvasScaler.ScaleWithScreenSize`, readable typography, progress bars/counters, clear
  primary actions, and palette-consistent panels. UI must remain readable at 1280x720 and 1920x1080.
- Disable or remove the copied `PrototypeSceneController` IMGUI debug panel in the finished game.
  `OnGUI`, loose debug labels, and unstyled test buttons do not count as player-facing UI. If no
  generated image asset is available, use restrained solid/translucent uGUI shapes and the built-in
  font; never leave gameplay unreadable behind placeholder patterns.
- Connect HUD values and screen visibility to actual runtime state. Health, objective/progress,
  currency/score/time, pause, choice, clear, failure, restart, and genre-specific controls must
  update from the systems they represent instead of displaying hard-coded sample text.
- When an upgrade can be previewed before purchase, its player-facing panel must show the current
  and projected post-upgrade values (`before -> after`) for every affected combat stat, including
  damage, attacks per second/cooldown, range, and splash radius when applicable. Use the same
  upgrade formula for the preview and the actual purchase so the displayed values cannot drift.
- Treat every sound item in `sound_asset_request.json` as a runtime integration contract. Preserve
  its `generation_spec.audio_cue`, raise that exact cue through `GameAudioCues.Raise(...)` at the
  successful gameplay transition (not merely on button click), and ensure the event fires once per
  transition. Tower construction, tower upgrade, enemy defeat, base damage, wave start, and boss
  arrival must remain distinct cues when requested. Imported/scene-bound audio without a matching
  gameplay raise is incomplete.
- Do not merely write a design, TODO, placeholder, or disconnected component.
- Treat every cached `UnityEngine.Object` reference as scene-lifetime state. Before accessing a
  cached component in `Update`, `FixedUpdate`, a coroutine, or an event callback, use Unity's
  destroyed-object-aware null check (`reference == null`) and either reacquire it from the current
  binding context/scene or return safely. Never access a Collider, Renderer, Transform, or other
  scene component retained from an unloaded scene.
- Editor-time `Configure(...)` calls are not serialized into the generated scene. For every
  generated genre controller, reacquire runtime dependencies in `Awake`/`Start` (for example,
  discover waypoint transforms, spawn points, economy/health modules, and HUD roots from the
  current scene) and keep serialized fields only as optional overrides. Never index a nullable
  collection such as `path[0]` before checking that it exists and has an element; if a required
  dependency is missing, build a visible degraded HUD and fail the action safely instead of
  throwing from `Update`. This is mandatory for tower-defense wave spawning and UI.
- Preserve image and sound binding keys from the asset request files.
- Put every public `MonoBehaviour` in its own `.cs` file whose filename exactly matches the class
  name. Generated game modules must derive from `GameModuleBehaviour`, implement
  `IGeneratedFeatureModule`, and declare the exact `[GeneratedGameModule("module_id")]` identity.
- Every concrete generated module class must itself be `public`; do not place multiple generated
  module classes behind a shared internal base in one source file. Unity must be able to serialize
  and reload each component in a fresh Editor process after the agent turn ends.
- Every concrete `GameModuleBehaviour` must implement
  `protected override void OnInitialize(GameContext context)` and register itself with
  `context.Register(this)`. Inspect the abstract base class before writing or repairing a module.
- Never create, edit, delete, or invent Unity `.meta` files manually. Never hand-edit
  `Assets/Scenes/Bootstrap.unity`. The host-owned `ModuleComponentCatalog`,
  `PrefabSceneAssembler`, and Unity importer create component bindings and scene serialization.
- Do not create, delete, or modify any `.asmdef` or `.asmref` file. Assembly layout and generated
  source directories are owned by the host pipeline. Never add `Assembly.Load` or other dynamic
  assembly discovery as a workaround for a missing generated module; fix the module source and
  its exact `GeneratedGameModule` identity instead.
- Preserve every already selected/generated module ID. A repair may not remove, rename, merge, or
  replace a working module merely to address a different runtime failure.
- Do not launch Unity Editor, Unity Hub, `Unity.exe`, a Unity batch-mode process, or a command
  that opens this project. Do not use the Unity CLI/pipeline/MCP to connect to or start an Editor.
  The host process exclusively owns Unity compilation, Play Mode tests, licensing, and project
  locking after this {agent_label} turn finishes.
- You may perform read-only/static inspection that does not start Unity. Report recommended Unity
  checks in the structured result instead of running them yourself.
"""
    (project_root / filename).write_text(text, encoding="utf-8", newline="\n")


def _implementation_prompt(
    design: GameLogicDesign,
    request: ParsedRequest,
    *,
    instruction_filename: str = "AGENTS.md",
) -> str:
    requirements = design.get("codex_harness_requirements", [])
    features = design.get("agent_harness_feature_requirements", [])
    return f"""Build the complete playable Unity game in the current project.

User request: {request["condition"]}
Genre: {request["genre"]}
Viewpoint: {request["viewpoint"]}
Agent-owned gameplay modules and mechanics: {json.dumps(requirements, ensure_ascii=False)}
Feature requirements: {json.dumps(features, ensure_ascii=False)}

Follow {instruction_filename}. First inspect the project and all generated design contracts. Then implement the
entire connected gameplay loop, not isolated sample scripts. Verify initialization values, scene
bindings, camera, controls, HUD, damage, progression, win/loss conditions, content counts, and the
user's requested mechanics. Reuse sound/image binding IDs instead of inventing incompatible IDs.
Do not accept a copied genre module or prototype scene as complete without tracing it against the
exact request. Replace stock behavior, layout, content, and tuning wherever it would make different
prompts produce substantially the same game. Keep only reusable infrastructure that genuinely
serves the requested design.
Remember that editor-time `Configure(...)` calls are not serialized into a saved scene. Reacquire
waypoints, spawn points, gameplay modules, and HUD references from the current scene in `Awake` or
`Start`, guard every collection/index before use, and keep the HUD visible in degraded mode when a
runtime dependency is missing. In particular, a tower-defense controller must never call
`path[0]` from `Update` until it has a non-null, non-empty route.
- For tower defense, start the first wave through a real player-facing control or a bounded
  preparation timer; the host smoke test may trigger `StartNextWave()` to skip that timer.
  Every build point must be inside the camera viewport and render above the floor/backdrop.
  Keep all requested build points visible and clickable, including those near HUD panels.
  Create exactly one EventSystem with a compatible UI input module. A world build-point click
  must select the point, reveal the build menu, and a real UI pointer click on a tower button
  must deduct gold and create a tower. Hide the build menu until a point is selected so its
  raycast target cannot cover build points. Add hover or selection feedback to build points.
  An enemy spawned by the wave must visibly traverse the path, and a built tower must damage
  and eventually defeat it. Preserve the public `WaveSpawnerModule` wave API when replacing
  the stock implementation, so the host can observe this sequence.
- Unity `Object` references have fake-null semantics after destruction. Do not use C# null
  coalescing (`GetComponent<T>() ?? AddComponent<T>()`) for scene components. Assign the result,
  test it with Unity's overloaded `component == null`, then call `AddComponent<T>()` if needed;
  re-check the result before accessing it. This is especially important for optional
  `LineRenderer`, collider, renderer, and UI components on build slots or dynamically-created
  gameplay objects.
Do not edit validation tests or immutable design/manifest JSON to make checks pass. Do not launch
Unity or use Unity CLI/pipeline/MCP commands; Unity validation is run only by the host after you
return. Return the required structured completion report after making the edits.
"""


def _repair_prompt(
    feedback: dict[str, Any], iteration: int, *, phase: str = "design_game_logic"
) -> str:
    return f"""Repair the Unity project using the host validator evidence below.

Repair iteration: {iteration}
Validation phase: {phase}
Evidence:
{json.dumps(feedback, ensure_ascii=False, indent=2)}

Read the referenced source definitions before editing. Fix root causes across files and bindings,
not only the first compiler line. Do not weaken tests or alter immutable generated design/manifest
JSON. Keep already working requested features intact. Do not create or modify `.meta` files or
hand-edit `Bootstrap.unity`; let the host assembler regenerate bindings. Do not create or modify
`.asmdef`/`.asmref` files and do not add dynamic `Assembly.Load` workarounds. Keep one public
MonoBehaviour per filename-matched `.cs` file and preserve every existing generated module ID.
Every generated module class must be public and individually serializable; split any file that
contains multiple `[GeneratedGameModule]` classes instead of keeping an internal class bundle.
When the phase is `validate_game` or `final_validation`, preserve generated and applied image/audio
files, their binding IDs, and asset manifests. Fix gameplay source, scene assembly, UI bindings,
initialization, and state transitions without replacing validated assets or reverting the game to
the copied genre prototype.
If a runtime exception reports a null route, spawn point, module, or HUD object, repair the source
by reacquiring that object at runtime and by adding an explicit null/empty guard; do not hide the
exception by disabling the wave, combat, or UI system.
If a runtime exception reports a missing component, replace null-coalescing component lookup with
an explicit Unity-aware null check and ensure the component is present on every object path that
can invoke the method.
If the tower-defense smoke test reports `runtime.tower_build_visibility`, position every build
point inside the camera view and set its SpriteRenderer sorting order above the background.
If it reports `runtime.tower_build_clickability` or `runtime.tower_build_input`, check the
build-point Collider2D, UI raycast coverage, EventSystem/input module, button listener, selected
point state, and gold deduction as one end-to-end pointer flow.
  Decorative HUD panels and text must set `raycastTarget = false`; only interactive controls
  may consume pointer input. Keep the build menu inactive until a build point is selected.
If it reports `runtime.tower_spawn`, inspect `StartNextWave`, the wave timer, enemy creation,
and the active scene; do not merely increase a timeout or suppress the scenario.
When repairing a quality-audit patch, inspect namespaces and assembly boundaries for every new
cross-file type. Add the correct `using` directive or fully qualify the type instead of deleting
the repaired behavior. Keep normal five-minute (or user-requested) pacing in authored settings;
accelerate only host test hooks and deterministic test scenarios.
Do not launch Unity Editor or run Unity,
Unity CLI/pipeline/MCP, or batch-mode commands; the host owns the next validation attempt. Return
the required structured report.
"""


def _validation_draft(project_root: Path, design: GameLogicDesign) -> dict[str, Any]:
    game_spec = design["game_spec"]
    entry_scene = (project_root / "Assets/Scenes/Bootstrap.unity").relative_to(
        project_root.parent.parent
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "generated",
        "engine": "Unity",
        "entry_scene": entry_scene.as_posix(),
        "required_image_asset_ids": [
            item["asset_id"]
            for item in game_spec["asset_requirements"]
            if item["asset_type"] == "image"
        ],
        "required_sound_asset_ids": [
            item["asset_id"]
            for item in game_spec["asset_requirements"]
            if item["asset_type"] == "sound"
        ],
    }


def _bounded_feedback(evidence: dict[str, Any]) -> dict[str, Any]:
    log_lines = [
        line
        for line in str(evidence.get("unity_log", "")).splitlines()
        if any(
            marker in line
            for marker in (
                "error CS",
                "Exception",
                "FAILED",
                "Error",
                "VALIDATION_FAIL",
                "UNITY_RUNTIME_SMOKE_FAILED",
                "UNITY_PLAYTEST_METRICS",
            )
        )
    ]
    return {
        "attempt": evidence["attempt"],
        "issues": evidence["issues"],
        "failed_checks": [item for item in evidence["checks"] if not item["passed"]],
        "diagnostics": "\n".join(log_lines)[-12000:],
    }


def _failure_signature(outcome: UnityValidationOutcome) -> str:
    """Identify the actual compiler/runtime transition, not the generic failed check label."""

    payload = {
        "issues": outcome.issues,
        "failed": [item for item in outcome.checks if not item["passed"]],
        "diagnostics": _signature_diagnostics(outcome.unity_log),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _signature_diagnostics(log: str) -> list[str]:
    diagnostics: list[str] = []
    for raw_line in log.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("UNITY_PLAYTEST_METRICS:"):
            try:
                metrics = json.loads(line.split(":", 1)[1])
            except json.JSONDecodeError:
                diagnostics.append(line[:1000])
                continue
            diagnostics.append(
                json.dumps(
                    {
                        "failed_transition": metrics.get("failed_transition", ""),
                        "validation_failures": metrics.get("validation_failures", []),
                        "unused_requested_features": metrics.get("unused_requested_features", []),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            continue
        if any(
            marker in line
            for marker in (
                "error CS",
                "VALIDATION_FAIL:",
                "UNITY_RUNTIME_SMOKE_FAILED:",
                "Scripts have compiler errors",
                "Access to the path",
                "Access is denied",
                "UnauthorizedAccessException",
                "FileNotFoundException",
                "Could not load the file",
                "executeMethod class",
                "executeMethod method",
                "threw exception",
                "unknown_module",
                "missing_module",
            )
        ):
            diagnostics.append(line[:1000])
    return sorted(set(diagnostics))[:40]


def _failure_severity(outcome: UnityValidationOutcome) -> int:
    if outcome.status == "passed":
        return 0
    evidence = "\n".join(
        [*(issue["message"] for issue in outcome.issues), outcome.unity_log[-16000:]]
    ).lower()
    if any(
        marker in evidence
        for marker in (
            "filenotfoundexception",
            "could not load the file",
            "unauthorizedaccessexception",
            "access is denied",
            "executeMethod class".lower(),
            "threw exception",
        )
    ):
        return 1100
    if "missing_module" in evidence or "unknown_module" in evidence:
        return 900
    if "error cs" in evidence or "scripts have compiler errors" in evidence:
        return 800
    target = classify_failure(outcome)["target"]
    return {
        "infrastructure": 1000,
        "binding": 700,
        "scene": 650,
        "code": 600,
        "level_plan": 500,
        "content_plan": 450,
        "balance_plan": 400,
        "test": 300,
    }[target]


_VALIDATION_MILESTONES = (
    "UNITY_MODULE_CATALOG_OK",
    "UNITY_GENERATED_FEATURE_BINDINGS_OK",
    "UNITY_IMPLEMENTATION_PLAN_OK",
    "UNITY_SCENE_ASSEMBLY_OK",
    "UNITY_GAME_BLUEPRINT_OK",
    "UNITY_LEVEL_PLAN_OK",
    "UNITY_GAMEPLAY_TUNING_OK",
    "UNITY_PRESENTATION_PLAN_OK",
    "UNITY_VALIDATION_PLAN_STATIC_OK",
    "UNITY_TEMPLATE_BUILD_OK",
    "UNITY_RUNTIME_SMOKE_OK",
)


def _validation_progress(outcome: UnityValidationOutcome) -> int:
    """Return the furthest host-owned Unity milestone reached by this source revision."""

    if outcome.status == "passed":
        return len(_VALIDATION_MILESTONES) + 1
    reached = [
        index
        for index, marker in enumerate(_VALIDATION_MILESTONES, start=1)
        if marker in outcome.unity_log
    ]
    return max(reached, default=0)


def _repair_is_regression(
    baseline: UnityValidationOutcome,
    candidate: UnityValidationOutcome,
    baseline_severity: int | None = None,
) -> bool:
    """Reject source changes only when Unity moved backward or worsened at the same stage."""

    baseline_progress = _validation_progress(baseline)
    candidate_progress = _validation_progress(candidate)
    if candidate_progress != baseline_progress:
        return candidate_progress < baseline_progress
    return _failure_severity(candidate) > (
        _failure_severity(baseline) if baseline_severity is None else baseline_severity
    )


def _normalize_windows_project_permissions(project_root: Path) -> dict[str, Any]:
    """Remove Codex sandbox ACLs from generated source roots before host Unity reads them."""

    if os.name != "nt":
        return {"status": "skipped", "reason": "non-Windows host"}
    results: list[dict[str, Any]] = []
    # Reset once from the project root. Resetting children again is redundant and can hide a
    # failure reported while walking an inaccessible descendant behind a later successful call.
    for relative in (".",):
        target = project_root / relative
        if not target.exists():
            continue
        try:
            completed = subprocess.run(
                ["icacls", str(target), "/reset", "/T", "/C", "/Q"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            results.append({"path": relative, "exit_code": -1, "diagnostic": str(error)})
            continue
        combined_output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        diagnostic_failure = _permission_diagnostic_failed(combined_output)
        results.append(
            {
                "path": relative,
                "exit_code": completed.returncode,
                "diagnostic": combined_output[-2000:],
                "diagnostic_failure": diagnostic_failure,
            }
        )
    access_probe = _probe_project_source_access(project_root)
    results.append(access_probe)
    failed = [
        item for item in results if item["exit_code"] != 0 or bool(item.get("diagnostic_failure"))
    ]
    return {"status": "warning" if failed else "normalized", "results": results}


def _permission_diagnostic_failed(output: str) -> bool:
    normalized = output.casefold()
    if any(
        marker in normalized
        for marker in (
            "access is denied",
            "access denied",
            "액세스가 거부되었습니다",
        )
    ):
        return True
    # icacls always prints a failure summary, including the successful
    # "Failed processing 0 files" case. Only a positive count is an error.
    if re.search(r"failed processing\s+([1-9]\d*)\s+files?", normalized):
        return True
    korean_failure = re.search(
        r"([1-9]\d*)\s*(?:개\s*)?파일[^\r\n]*처리하지 못했습니다", normalized
    )
    return korean_failure is not None


def _prepare_host_owned_source_roots(project_root: Path) -> None:
    """Create Codex write targets before the sandbox can assign restrictive directory ACLs."""

    for relative in (
        "Assets/GameTemplate/Generated/Scripts",
        "Assets/GameTemplate/Generated/Validation",
    ):
        (project_root / relative).mkdir(parents=True, exist_ok=True)


def _probe_project_source_access(project_root: Path) -> dict[str, Any]:
    """Verify the host can enumerate and read the files Unity must import."""

    inspected = 0
    try:
        for relative in ("Assets", "Packages", "ProjectSettings"):
            root = project_root / relative
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                inspected += 1
                if path.suffix.casefold() in {".cs", ".asmdef", ".asmref", ".json"}:
                    with path.open("rb") as source:
                        source.read(1)
    except OSError as error:
        return {
            "path": "host_read_probe",
            "exit_code": -1,
            "diagnostic": f"{type(error).__name__}: {error}",
            "diagnostic_failure": True,
            "inspected_files": inspected,
        }
    return {
        "path": "host_read_probe",
        "exit_code": 0,
        "diagnostic": f"Host enumerated {inspected} project files",
        "diagnostic_failure": False,
        "inspected_files": inspected,
    }


def _require_normalized_permissions(report: dict[str, Any], phase: str) -> None:
    if report.get("status") == "warning":
        failures = [
            item
            for item in report.get("results", [])
            if item.get("exit_code") != 0 or item.get("diagnostic_failure")
        ]
        raise RuntimeError(
            "CODEX_PROJECT_PERMISSION_FAILED "
            f"{phase}: Unity source paths remain inaccessible after ACL normalization: "
            f"{failures}"
        )
