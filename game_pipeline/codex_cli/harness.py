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
        "host_validation_pending": {"type": "boolean"},
        "implementation_blockers": {"type": "array", "items": {"type": "string"}},
        "visual_objects": {
            "type": "array",
            "maxItems": 64,
            "items": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string"},
                    "scene_object_prefix": {"type": "string"},
                    "purpose": {"type": "string"},
                    "description": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "sprite",
                            "ui",
                            "background",
                            "tileset",
                            "illustration",
                            "portrait",
                        ],
                    },
                },
                "required": [
                    "asset_id",
                    "scene_object_prefix",
                    "purpose",
                    "description",
                    "kind",
                ],
                "additionalProperties": False,
            },
        },
        "sound_events": {
            "type": "array",
            "maxItems": 64,
            "items": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string"},
                    "cue_id": {"type": "string"},
                    "purpose": {"type": "string"},
                    "description": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["bgm", "sfx", "ui", "voice", "ambience"],
                    },
                },
                "required": ["asset_id", "cue_id", "purpose", "description", "kind"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "status",
        "summary",
        "changed_files",
        "implemented_features",
        "tests_run",
        "unresolved_requirements",
        "recommended_validation",
        "host_validation_pending",
        "implementation_blockers",
        "visual_objects",
        "sound_events",
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
        if _staged_implementation_enabled(design):
            try:
                prompt = self._run_source_checkpoint(project_root, design, request, prompt)
            except Exception as error:  # noqa: BLE001 - fall back to the full implementation turn
                self._record(
                    f"{self.provider}_source_checkpoint_unavailable",
                    {"error": f"{type(error).__name__}: {error}"},
                )
                prompt = (
                    "An optional source checkpoint could not complete. Inspect the current "
                    "project state and finish the whole requested game.\n\n" + prompt
                )
        self.implementation = self.runner.run(
            project_root=project_root,
            prompt=prompt,
            schema=COMPLETION_SCHEMA,
            audit_directory=self.audit_root / "implementation",
        )
        _require_agent_completion(
            self.implementation,
            "initial implementation",
            allow_host_validation_pending=True,
        )
        permission_report = _normalize_windows_project_permissions(project_root)
        self._record(f"{self.provider}_project_permissions_after_implementation", permission_report)
        _require_normalized_permissions(
            permission_report, f"after {self.agent_label} implementation"
        )
        self._record(f"{self.provider}_implementation", self.implementation.final_response)
        return self.implementation

    def _run_source_checkpoint(
        self,
        project_root: Path,
        design: GameLogicDesign,
        request: ParsedRequest,
        prompt: str,
    ) -> str:
        editor = UnityProjectValidator.find_unity_editor(
            UnityProjectValidator._read_project_version(project_root)
        )
        if editor is None or not editor.is_file():
            return prompt
        scaffold = self.runner.run(
            project_root=project_root,
            prompt=_compilable_foundation_prompt(
                design, request, instruction_filename=self.instruction_filename
            ),
            schema=COMPLETION_SCHEMA,
            audit_directory=self.audit_root / "source_foundation",
        )
        self._record(f"{self.provider}_source_foundation", scaffold.final_response)
        compiler = UnityProjectValidator(
            mode="required",
            unity_editor=editor,
            timeout_seconds=int(os.environ.get("MAINFLOW_UNITY_VALIDATION_TIMEOUT_SECONDS", "300")),
        )
        compile_outcome = compiler.compile_sources(project_root)
        self._record_source_checkpoint(0, compile_outcome)
        for repair_attempt in range(1, 3):
            if compile_outcome.status == "passed":
                break
            if any(
                issue["code"] in {"UNITY_SOURCE_COMPILATION_UNAVAILABLE", "UNITY_EDITOR_NOT_FOUND"}
                for issue in compile_outcome.issues
            ):
                break
            repair = self.runner.run(
                project_root=project_root,
                prompt=(
                    "Fix only the Unity C# source compilation errors in the current project. "
                    "Read the class definitions before editing. Preserve the requested game "
                    "design and do not edit tests or generated contracts. The host will run "
                    "Unity after you return.\n\n" + compile_outcome.unity_log[-12000:]
                ),
                schema=COMPLETION_SCHEMA,
                audit_directory=(
                    self.audit_root / "source_foundation" / f"compile_repair_{repair_attempt}"
                ),
            )
            self._record(
                f"{self.provider}_source_checkpoint_repair_{repair_attempt}",
                repair.final_response,
            )
            compile_outcome = compiler.compile_sources(project_root)
            self._record_source_checkpoint(repair_attempt, compile_outcome)
        return (
            "Continue from the existing Unity source foundation. Complete every requested "
            "gameplay, scene, HUD, and content requirement. The host source checkpoint result "
            "is included below; address any remaining compiler errors while completing the "
            "game.\n\n"
            + json.dumps(
                {
                    "checks": compile_outcome.checks,
                    "diagnostics": _signature_diagnostics(compile_outcome.unity_log),
                },
                ensure_ascii=False,
            )
            + "\n\n"
            + prompt
        )

    def _record_source_checkpoint(self, attempt: int, outcome: UnityValidationOutcome) -> None:
        self._record(
            f"{self.provider}_source_checkpoint_{attempt}",
            {
                "checks": outcome.checks,
                "issues": outcome.issues,
                "diagnostics": _signature_diagnostics(outcome.unity_log),
            },
        )

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
Read `Assets/GameTemplate/Generated/Design/pacing_contract.json` and `ui_contract.json` before
patching. For duration gaps, add real authored challenges or decisions rather than waiting.
For UI gaps, bind a visible control or value to the actual gameplay state and transition.
Never repair pacing by adding a minimum-time gate at a zone boundary or the goal.
For contact-damage findings, compare player health before and after a nonlethal hit. Preserve
the reduced health and temporary invulnerability while play continues. Only trigger checkpoint
respawn on zero health, falling, an explicit timeout, or a lethal stage hazard. If a copied
`PrototypeHazard` calls `Respawn()` after every `Damage()`, correct that behavior and verify the
health-zero transition still reaches the checkpoint. Keep the existing Unity smoke checks intact.
If the only unfinished step is host-owned Unity validation, put it in
`recommended_validation` and report `status=completed` after making the source edits.
Use `needs_attention` only for implementation work you could not finish.
Set `host_validation_pending=true` when Unity compilation or Play Mode must be run by the
host. Put only unfinished source implementation in `implementation_blockers` and
`unresolved_requirements`; leave both arrays empty for host-only validation.
Return the required structured report.
"""
        try:
            result = self.runner.run(
                project_root=project_root,
                prompt=prompt,
                schema=COMPLETION_SCHEMA,
                audit_directory=self.audit_root / "quality_repair" / f"attempt_{iteration:02d}",
            )
            _require_agent_completion(
                result, f"quality repair {iteration}", allow_host_validation_pending=True
            )
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
                    from game_pipeline.requirement_constraints import forbids_player_projectiles

                    results, checklist_log = workflow._run_tests(
                        project_root,
                        checklist,
                        excluded_static_feature_ids=(
                            {"FC03"} if forbids_player_projectiles(request["condition"]) else set()
                        ),
                    )
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
        phase_budget = _validation_time_budget(phase, self.settings.total_timeout_seconds)
        deadline = started + phase_budget
        attempts: list[dict[str, Any]] = []
        repairs: list[CodexCliResult] = []
        signature_counts: dict[str, int] = {}
        distinct_signatures: set[str] = set()
        best_ui_metrics: _UiQualityMetrics | None = None
        improving_signatures: set[str] = set()
        pending_snapshot: _ProjectSourceSnapshot | None = None
        pending_baseline_outcome: UnityValidationOutcome | None = None
        pending_baseline_evidence: dict[str, Any] | None = None
        pending_baseline_severity: int | None = None
        repair_limit = self.settings.max_repairs if max_repairs is None else max_repairs
        adaptive_repairs = repair_limit > 0 and phase in {
            "design_game_logic",
            "validate_game",
            "final_validation",
        }
        hard_repair_limit, repair_extension = _adaptive_repair_limits(repair_limit)
        active_repair_limit = repair_limit
        attempt = 0
        while attempt <= active_repair_limit:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"{phase} exceeded its {phase_budget}s validation budget "
                    "before the next Unity check"
                )
            outcome = (
                initial_outcome
                if attempt == 0 and initial_outcome is not None
                else validator.validate(project_root, draft, request, time_budget_seconds=remaining)
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
            ui_metrics = _ui_quality_metrics(outcome.unity_log)
            if ui_metrics is not None:
                if best_ui_metrics is not None and _ui_quality_improved(
                    best_ui_metrics, ui_metrics
                ):
                    signature_counts[signature] = 0
                    improving_signatures.add(signature)
                    self._record(
                        f"{self.provider}_{phase}_ui_layout_progress_{attempt}",
                        {
                            "previous": best_ui_metrics.__dict__,
                            "current": ui_metrics.__dict__,
                        },
                    )
                    print(
                        "[AGENT][repair] HUD 안전영역 또는 텍스트 넘침 오류가 감소했습니다.",
                        flush=True,
                    )
                if best_ui_metrics is None or _ui_quality_improved(best_ui_metrics, ui_metrics):
                    best_ui_metrics = ui_metrics
            signature_count = signature_counts.get(signature, 0) + 1
            signature_counts[signature] = signature_count
            distinct_signatures.add(signature)
            if signature_count >= 3:
                raise RuntimeError(
                    f"{self.agent_label} repair stopped because the same root Unity failure "
                    "was found three times despite source repairs: "
                    f"{outcome.issues}; diagnostics={_signature_diagnostics(outcome.unity_log)}"
                )
            if attempt >= active_repair_limit:
                if (
                    adaptive_repairs
                    and attempt < hard_repair_limit
                    and (len(distinct_signatures) > 1 or signature in improving_signatures)
                ):
                    previous_limit = active_repair_limit
                    active_repair_limit = min(
                        hard_repair_limit,
                        active_repair_limit + repair_extension,
                    )
                    extension_evidence = {
                        "reason": "validation is still exposing a repairable failure",
                        "previous_limit": previous_limit,
                        "extended_limit": active_repair_limit,
                        "hard_limit": hard_repair_limit,
                        "failure_signature_count": signature_count,
                        "distinct_failure_count": len(distinct_signatures),
                        "diagnostics": _signature_diagnostics(outcome.unity_log),
                    }
                    self._record(
                        f"{self.provider}_{phase}_repair_budget_extended_{attempt}",
                        extension_evidence,
                    )
                    print(
                        "[AGENT][repair] 서로 다른 검증 오류가 계속 발견되어 "
                        f"수리 한도를 {previous_limit}회에서 "
                        f"{active_repair_limit}회로 자동 연장합니다.",
                        flush=True,
                    )
                else:
                    raise RuntimeError(
                        f"{self.agent_label} Unity validation failed after {attempt} repairs: "
                        f"{outcome.issues}; "
                        f"diagnostics={_signature_diagnostics(outcome.unity_log)}"
                    )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"{phase} exceeded its {phase_budget}s validation budget after Unity check"
                )
            feedback = _bounded_feedback(evidence)
            ui_guidance = _ui_layout_repair_guidance(outcome.unity_log)
            if ui_guidance:
                feedback["ui_layout_corrections"] = ui_guidance
            opacity_guidance = _ui_opacity_violations(outcome.unity_log)
            if opacity_guidance:
                feedback["ui_opacity_corrections"] = opacity_guidance
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
                f"[AGENT][repair] Unity 검증 오류 수정 {attempt + 1}/{active_repair_limit}: "
                f"{failure_summary}",
                flush=True,
            )
            try:
                repair = self.runner.run(
                    project_root=project_root,
                    prompt=_repair_prompt(feedback, attempt + 1, phase=phase),
                    schema=COMPLETION_SCHEMA,
                    audit_directory=self.audit_root / phase / f"repair_{attempt + 1:02d}",
                    timeout_seconds=min(self.settings.invocation_timeout_seconds, remaining),
                )
                _require_agent_completion(
                    repair,
                    f"{phase} repair {attempt + 1}",
                    allow_host_validation_pending=True,
                )
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
            attempt += 1
        raise AssertionError("unreachable")

    def _record(self, name: str, value: Any) -> None:
        if self.record is not None:
            self.record(name, value)


def _require_agent_completion(
    result: CodexCliResult, phase: str, *, allow_host_validation_pending: bool = False
) -> None:
    """Stop immediately when the CLI reports that it could not inspect or edit the project."""

    response = result.final_response
    blockers = response.get("implementation_blockers", [])
    unresolved = response.get("unresolved_requirements", [])
    if (
        response.get("status") == "completed"
        and not blockers
        and isinstance(unresolved, list)
        and all(
            _is_host_only_note(item)
            or (
                allow_host_validation_pending
                and response.get("host_validation_pending") is True
                and _is_explicit_unity_validation_note(item)
            )
            for item in unresolved
        )
    ):
        return
    if allow_host_validation_pending and _only_host_validation_pending(response):
        return
    summary = str(response.get("summary", "Agent could not complete the requested work"))
    detail = "; ".join(str(item) for item in unresolved[:5]) if isinstance(unresolved, list) else ""
    suffix = f" Unresolved: {detail}" if detail else ""
    raise RuntimeError(f"AGENT_IMPLEMENTATION_INCOMPLETE ({phase}): {summary}.{suffix}")


def _only_host_validation_pending(response: dict[str, Any]) -> bool:
    """Allow edited source to reach the host-owned Unity validation gate."""

    changed = response.get("changed_files")
    unresolved = response.get("unresolved_requirements")
    if response.get("status") != "needs_attention" or not isinstance(changed, list) or not changed:
        return False
    if not isinstance(unresolved, list):
        return False
    if "host_validation_pending" in response:
        if response["host_validation_pending"] is not True:
            return False
        blockers = response.get("implementation_blockers")
        if not isinstance(blockers, list) or blockers:
            return False
        return all(
            _is_host_only_note(item) or _is_explicit_unity_validation_note(item)
            for item in unresolved
        )
    return bool(unresolved) and all(_is_host_validation_note(item) for item in unresolved)


def _is_host_only_note(item: Any) -> bool:
    if _is_host_validation_note(item):
        return True
    if not isinstance(item, str) or "\n" in item:
        return False
    normalized = " ".join(item.lower().split())
    return (
        "format" in normalized
        and any(tool in normalized for tool in ("ruff", "csharpier"))
        and not any(
            concern in normalized for concern in ("source", "implementation", "compile", "invalid")
        )
        and any(
            status in normalized for status in ("unavailable", "not installed", "could not run")
        )
    )


def _is_explicit_unity_validation_note(item: Any) -> bool:
    """The explicit host flag permits a brief pending Unity check without a host suffix."""

    if not isinstance(item, str) or "\n" in item:
        return False
    normalized = " ".join(item.lower().split()).rstrip(".")
    return (
        normalized.startswith("unity ")
        and any(word in normalized for word in ("validation", "compilation", "play mode"))
        and normalized.endswith(("is pending", "remains pending", "has not been run"))
    )


def _is_host_validation_note(item: Any) -> bool:
    """Accept legacy host-only notes without treating source gaps as host work."""

    if not isinstance(item, str) or "\n" in item:
        return False
    normalized = " ".join(item.lower().split())
    if any(
        word in normalized
        for word in (
            "failed",
            "broken",
            "missing",
            "incomplete",
            "cannot",
            "unable",
            "not implemented",
            "not wired",
            "not connected",
        )
    ):
        return False
    return (
        any(word in normalized for word in ("host", "project instruction"))
        and "unity" in normalized
        and any(word in normalized for word in ("validat", "test", "compil", "play mode"))
        and any(
            word in normalized
            for word in (
                "pending",
                "remain",
                "required",
                "needed",
                "not run",
                "not executed",
                "not been verified",
                "not verified",
                "unverified",
            )
        )
    )


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


def _adaptive_repair_limits(initial_limit: int) -> tuple[int, int]:
    """Return a bounded hard limit and extension size for progressive validation failures."""

    hard_limit_name = "MAINFLOW_AGENT_HARD_MAX_REPAIRS"
    extension_name = "MAINFLOW_AGENT_REPAIR_EXTENSION"
    try:
        configured_hard_limit = int(os.environ.get(hard_limit_name, "8"))
        extension = int(os.environ.get(extension_name, "2"))
    except ValueError as error:
        raise ValueError(f"{hard_limit_name} and {extension_name} must be integers") from error
    if not 1 <= configured_hard_limit <= 24:
        raise ValueError(f"{hard_limit_name} must be between 1 and 24")
    if not 1 <= extension <= 6:
        raise ValueError(f"{extension_name} must be between 1 and 6")
    return max(initial_limit, configured_hard_limit), extension


def _validation_time_budget(phase: str, total_timeout_seconds: int) -> int:
    name = (
        "MAINFLOW_AGENT_FINAL_VALIDATION_BUDGET_SECONDS"
        if phase == "final_validation"
        else "MAINFLOW_AGENT_VALIDATION_BUDGET_SECONDS"
    )
    default = 1500 if phase == "final_validation" else 1800
    try:
        configured = int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 60 <= configured <= 21600:
        raise ValueError(f"{name} must be between 60 and 21600")
    return min(configured, total_timeout_seconds)


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
Read `game/design/pacing_contract.json` and `game/design/ui_contract.json`. Verify required
collectibles, checkpoints, and the goal are reachable in the authored scene. Check normal human
play duration from authored encounters and traversal, not accelerated smoke-test time or an idle
countdown. Report estimated total playtime gaps as info-level findings, never as a sole release
failure; a real-control timing trace is needed for a reliable duration judgment. Never recommend
delaying progression at zone boundaries to meet a timer. Check every HUD region, state
screen, live value binding, and primary action against runtime source and scene wiring.
Inspect `visual_validation_result.ui_readability` and its post-asset screenshot when present.
Off-screen text, missing backing panels, and low contrast are concrete UI defects even if the
optional VLM comparison is disabled. An unavailable capture is only missing evidence.
Compare the 1280x720 and 1920x1080 HUD audit findings. Inspect applied background art for
obvious oversized source pixels or stretched single-image coverage; request a tiled or
appropriately detailed source when the actual game camera exposes these defects.
If visual validation was deliberately disabled or skipped because the image backend produced
placeholders, record the missing VLM comparison only as an info-level limitation; do not fail the
game solely for that skip. Judge actual readability and visual defects separately.
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
- Map each explicit request clause to a concrete scene instance, runtime transition, HUD/control
  binding, or audio cue before coding. A script class alone does not satisfy a requested enemy,
  hazard, collectible, checkpoint, or tutorial object.
- Derive the connected core loop, world layout, content placement, progression, camera behavior,
  HUD, win/loss flow, and feedback from the exact user request. Avoid fixed sample coordinates and
  fixed genre-demo sequences when they are not justified by that request.
- Scope moving hazards, collapse zones, countdown failures, and automatic respawns to their
  authored area. Entering a final challenge must not make its hazard damage or reset the player
  in an earlier zone; checkpoint recovery must restore the relevant zone and timer state. Test
  ordinary contact damage again after leaving or respawning from a timed challenge.
- A nonlethal enemy or hazard hit must reduce the player's remaining health and allow play to
  continue with the requested invulnerability. Checkpoint recovery occurs when health reaches
  zero, the player falls, a timer expires, or an explicitly lethal stage hazard is touched.
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
- This Unity directory is generated output. The host formats tracked repository source; do not
  run the parent repository's `tools/format_repo.py` over generated project files. If a formatter
  is unavailable here, record that in `tests_run` rather than `unresolved_requirements`.
- Prefer project APIs already present. Inspect definitions before referencing a class, member, tag, layer, or package.
- You may refactor copied runtime gameplay modules, prototype controllers, and copied editor-side
  assembly code when necessary for a request-specific game. Preserve the host validation entry
  points, immutable generated contracts, asset binding keys, tests, and project/package identity.
- Implement behavior in source files and connect it to actual scene objects, UI, progression, win/loss flow, and feedback.
- Keep exactly one active Player object and one authoritative movement controller. The assembled
  scene already contains Player and TopDownMovementModule: bind that module to the same
  Rigidbody2D observed by the camera, health, enemies, and validation. Never create a second
  Player from a timer, spawner, or presentation controller. Preserve WASD/arrow input through
  InputAdapterModule instead of driving a different body in parallel.
- Treat `presentation_plan.json` as an implementation contract, not mood-board text. Build a
  coherent Unity uGUI hierarchy for every specified HUD region and state screen, with anchored
  layout, `CanvasScaler.ScaleWithScreenSize`, readable typography, progress bars/counters, clear
  primary actions, and palette-consistent panels. UI must remain readable at 1280x720 and 1920x1080.
- Treat `ui_contract.json` as an executable UI checklist: every HUD region has a live gameplay
  state source, every required state screen opens on its actual transition, and each primary
  action works. Inspect the game at both reference resolutions and keep world interaction
  points clickable outside HUD raycast areas.
- Enumerate every value the user explicitly requests on screen and show each one in the live
  playing HUD. For SurvivorLike this includes the current kill count as enemies die; showing
  kills only on the result screen is insufficient. Bind each counter to its authoritative
  runtime state and verify that it changes at the corresponding gameplay transition.
- For each HUD panel, use anchor and offset pairs that keep its visible RectTransform inside
  the screen at 1280x720 and 1920x1080. In a top-left panel, both x offsets should be small
  positive insets; do not combine a fractional-width anchor with a large positive right offset.
  Give labels, health/XP bars, and timer separate non-overlapping rows inside their panels.
- If a HUD helper accepts `(position, size)`, its second Vector2 is width and height,
  not the far corner. Compute `size = maxCorner - minCorner` before passing corner
  coordinates. Check the actual RectTransform world corners after Canvas scaling;
  leave several screen pixels beyond the required safe inset for rounding.
- Before finishing a HUD, calculate each label and gauge rectangle in the panel's local
  coordinates. Account for its anchors, pivot, width and height; the right edge of a
  left-anchored child is `anchoredPosition.x + sizeDelta.x` when its pivot.x is zero.
  Reserve separate rows for status, gauges, and timers. If they do not all fit within
  the panel's 15-percent border inset (capped at 40 screen pixels), split the panel
  instead of placing a timer beyond its right edge. Check every child, not just the
  first one, at the CanvasScaler reference resolution.
- Keep every live HUD label at least 14px. Set both Text overflow modes to Wrap or
  Truncate, never Overflow. Give wrapped text enough height to remain readable;
  shrinking the font below 14px or merely clipping required values is not a layout fix.
  The safe width is panel width minus twice its 15-percent inset (capped at 40 screen
  pixels per side). Size status text, health/XP bars, and icons to that width before
  creating their RectTransforms; split a crowded panel into separate panels.
- Put each live HUD text group and transient announcement inside an anchored uGUI panel with
  a solid dark `UnityEngine.UI.Image` backing (alpha 1.0). HUD, menu and button backings
  must be opaque even when initially inactive; do not use 0.95, 0.96, 0.97, or 0.99 for
  `HudArt_` or text-bearing panel Images. Reserve alpha fades for transient effects only.
  Keep text colors
  high contrast, padding around every label, and panels inside the visible screen at both
  reference resolutions. Do not place white or warning text directly over world artwork.
  Keep decorative Images `raycastTarget = false`; interactive Button graphics alone receive
  raycasts. Counter text, bars, and button labels remain live Unity UI, never rasterized art.
- Keep the player's sprite visible during hit feedback. Use a tint, outline, or alpha pulse
  with a visible silhouette instead of disabling its only SpriteRenderer for repeated frames.
- Add a non-interactive `UnityEngine.UI.Image` child named `HudArt_...` behind text within each
  HUD panel; the host will bind the optional `hud_panel_frame` artwork after generation. Use
  the `HudArt_...` RectTransform itself as the parent for its live text, gauges, and buttons,
  or put both the decoration and content under one shared panel RectTransform. Do not leave
  live content as unrelated children of the Canvas and rely on screen position alone. Use
  the exact `HudIconHealth`, `HudIconCurrency`, `HudIconWave`, `HudIconTimer`, and
  `HudIconObjective` prefixes only for icons requested in `image_asset_request.json`. Their
  Image components must stay within their panel and must not consume pointer input. Preserve
  the dark panel fallback and legible text if generated artwork is unavailable or too bright.
  Treat the artwork as a nine-slice decoration: its source pixel dimensions do not define the
  panel's layout. The image reserves the middle 70 percent for live content. Place every label,
  gauge and button inside an inset content RectTransform, at least 15 percent of panel width
  and height from the visible border (up to 40 screen pixels per side). Enlarge or split a panel
  when its content cannot fit inside that safe rectangle; never let text or bars overlap frame
  ornaments. The `HudArt_` image may be the panel itself or a child behind content. Keep this
  safe rectangle and an opaque dark backing even when artwork is absent.
- Treat `pacing_contract.json` as the normal human-play contract. Author traversal, enemy,
  obstacle, wave, or decision content in each segment to reach its target duration. A long
  idle countdown, movement-against-a-wall gate, and a fast automated smoke test are not evidence
  of a full-length game. Never block a zone exit or goal solely until a minimum time has elapsed.
  Check spawn-to-goal route continuity and place every required collectible and checkpoint
  within the implemented movement envelope. The host records normal-run duration when a real
  controls playtest is available; author content that supports the target without artificial gates.
- Disable or remove the copied `PrototypeSceneController` IMGUI debug panel in the finished game.
  `OnGUI`, loose debug labels, and unstyled test buttons do not count as player-facing UI. If no
  generated image asset is available, use restrained solid uGUI shapes and the built-in
  font; never leave gameplay unreadable behind placeholder patterns.
- Connect HUD values and screen visibility to actual runtime state. Health, objective/progress,
  currency/score/time, pause, choice, clear, failure, restart, and genre-specific controls must
  update from the systems they represent instead of displaying hard-coded sample text.
- For every offered SurvivorLike upgrade, set `UpgradeDefinition.observableStatId` to a
  request-specific numeric gameplay value and `expectedStatChange` to `increase`, `decrease`,
  or `change`. Preserve these fields on `UpgradeDefinition` even when replacing its source.
  The component that owns that live value must implement
  `IGameplayStatSource.TryGetGameplayStat(statId, out value)` and expose it before and after
  selection. A bow may expose draw speed, a gun magazine capacity, or a melee weapon reach.
  Never report selection counts, UI text, or parallel bookkeeping as the effect. Map every
  blueprint progression option as well as options added in code. Blueprint options without
  an observable stat are omitted in Agent Harness mode; populate a request-specific pool
  with at least three actual choices rather than relying on copied sample options.
  Apply the selected effect
  directly or through a subscribed `Selected` handler; a button calling `Select(index)` alone
  is incomplete.
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
- In the structured completion response, fill `visual_objects` with one entry per visually
  distinct object explicitly requested by the user or newly authored in this game that is
  absent from `image_asset_request.json`. Include enemies/variants, hazards, pickups,
  landmarks, bases, projectiles, and interactive props when they need different artwork.
  Use a stable lowercase ASCII `asset_id` (for example `visual_clockwork_drone`), a specific
  `scene_object_prefix` matching the actual GameObject or prefab name, a concrete image
  purpose/description, and an image kind. Repeated instances share one entry. Never list an
  object solely because a genre preset mentions it; use the user's condition and authored
  content. If no additional object art is needed, return an empty array.
- For a request-specific UI icon or ornament absent from the image request, include it in
  `visual_objects` with `kind="ui"` and make `scene_object_prefix` match the actual uGUI
  Image name. The host binds UI art to Image components by that prefix; do not replace live
  labels or buttons with a flattened screenshot.
- For runtime-spawned objects, look up their `asset_id` with `AssetRegistryModule.TryGet<Sprite>`
  when a sprite is available and retain a clean primitive fallback until import. The host
  generates and imports `visual_objects` after implementation, so never invent a second
  image service call inside Unity.
- In the structured completion response, fill `sound_events` with distinct sounds needed by
  the user's condition or the gameplay you authored but absent from `sound_asset_request.json`.
  Use stable lowercase ASCII `asset_id` and `cue_id` values (for example
  `clockwork_gate_open_sfx` and `clockwork_gate_open`), describe the audible event precisely,
  and choose `bgm`, `sfx`, `ui`, `voice`, or `ambience`. Do not duplicate an existing sound ID
  or audio cue. Wire `GameAudioCues.Raise("cue_id")` into the successful runtime transition,
  once per event; a proposed sound without a reachable raise is incomplete. The host imports
  these clips after implementation. Return an empty array when no new sound is needed.
- For tower defense, give every unoccupied build slot the requested `tower_build_slot`
  artwork. Keep its scene object name prefixed `TowerBuildSlot_` or `BuildPoint_` so the
  post-generation asset binder can replace the temporary marker. An occupied slot must
  display the built tower clearly rather than retaining the empty-slot appearance.
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
- `GameBootstrap` initializes `GameTemplateConfig.asset` selected modules in list order.
  Any service read by `context.GetRequired<T>()` during `OnInitialize` must be registered by
  an earlier selected module; keep prerequisite modules before their consumers.
- Do not launch Unity Editor, Unity Hub, `Unity.exe`, a Unity batch-mode process, or a command
  that opens this project. Do not use the Unity CLI/pipeline/MCP to connect to or start an Editor.
  The host process exclusively owns Unity compilation, Play Mode tests, licensing, and project
  locking after this {agent_label} turn finishes.
- You may perform read-only/static inspection that does not start Unity. Report recommended Unity
  checks in the structured result instead of running them yourself.
"""
    (project_root / filename).write_text(text, encoding="utf-8", newline="\n")


def _staged_implementation_enabled(design: GameLogicDesign) -> bool:
    setting = os.environ.get("MAINFLOW_AGENT_STAGED_IMPLEMENTATION", "auto").strip().lower()
    if setting in {"0", "false", "off"}:
        return False
    if setting in {"1", "true", "on"}:
        return True
    if setting != "auto":
        raise ValueError("MAINFLOW_AGENT_STAGED_IMPLEMENTATION must be auto, on, or off")
    features = design.get("agent_harness_feature_requirements", [])
    return isinstance(features, list) and len(features) >= 24


def _compilable_foundation_prompt(
    design: GameLogicDesign,
    request: ParsedRequest,
    *,
    instruction_filename: str,
) -> str:
    return f"""Prepare the compile-safe C# foundation for the complete Unity game.

User request: {request["condition"]}
Genre: {request["genre"]}
Feature requirements: {json.dumps(design.get("agent_harness_feature_requirements", []), ensure_ascii=False)}

Read {instruction_filename} and the generated design contracts. Implement the shared runtime
state, component interfaces, and cross-script dependencies for the requested mechanics first.
Build enough real behavior to establish the connected core loop. This is an intermediate source
checkpoint: the host will compile the project now, and a second agent turn will finish scene
content, HUD, polish, and remaining mechanics. Do not use dummy no-op implementations to hide
missing behavior. Do not launch Unity, edit tests, or change generated contracts. Return the
required structured completion report, listing deferred game requirements in
`unresolved_requirements` and setting `host_validation_pending=true`.
"""


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

The completion response must include `visual_objects`: request-specific visible object art
that the current image asset request omits. Match every `scene_object_prefix` to an authored
scene object/prefab (or to the name prefix used by runtime spawning code), and use the same
`asset_id` when runtime code retrieves the generated sprite from AssetRegistryModule. Do not
list each instance separately or duplicate existing image asset IDs.
Treat UI artwork as separate optional panel or icon sprites. Name the corresponding
`UnityEngine.UI.Image` elements with the requested `HudArt_` or `HudIcon...` prefixes, keep
all live text and buttons above the decorative art, and make the fallback panels readable.
The completion response must also include `sound_events`: distinct request-specific sounds
missing from the sound asset request. Each `cue_id` must already be raised by actual gameplay
code through `GameAudioCues.Raise` at the event it describes. Reuse existing cue IDs and omit
duplicates. Return an empty array if the request needs no extra sound.

Before coding, read `Assets/GameTemplate/Generated/Design/pacing_contract.json` and
`Assets/GameTemplate/Generated/Design/ui_contract.json`. Preserve the requested normal
playtime, connect every required collectible and checkpoint to the real traversable route,
and make each HUD value and result screen reflect the current runtime state.
For each SurvivorLike upgrade, set `UpgradeDefinition.observableStatId` and
`expectedStatChange` and expose the corresponding live value from its authoritative
gameplay component through `IGameplayStatSource`. Keep blueprint progression options
and any code-added choices consistent with that contract for any requested weapon type.
Keep timed or rising hazards local to their authored zone. A player teleported or respawned into
an earlier zone must still take ordinary enemy and trap damage without the final-zone controller
immediately overriding that contact or resetting the player.
For SurvivorLike, reuse the assembled scene Player and its TopDownMovementModule. Do not turn
GameTimerModule into a second player/world bootstrap or attach another movement loop to a
different Rigidbody2D. Verify that InputAdapterModule movement changes the visible Player's
position, then that the camera and enemies track that same transform.

Follow {instruction_filename}. First inspect the project and all generated design contracts. Then implement the
entire connected gameplay loop, not isolated sample scripts. Verify initialization values, scene
bindings, camera, controls, HUD, damage, progression, win/loss conditions, content counts, and the
user's requested mechanics. Reuse sound/image binding IDs instead of inventing incompatible IDs.
Keep the exact number of requested objects in the design plan, authored scene, HUD, and result;
never silently truncate generated placements. Confirm each requested object type has an active
scene instance and a reachable interaction path.
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
  Anchor the build menu inside the bottom-right screen corner: for a fixed-size panel use
  anchor and pivot `(1, 0)` with a negative X and positive Y inset. Keep every tower-choice
  button fully within the 1280x720 viewport, visible, interactable, and unobstructed by
  another UI Graphic. Do not rely on direct `TryBuild` calls as proof that the menu works.
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
Set `host_validation_pending=true` for host-owned Unity checks. Put actual unfinished source
work in `implementation_blockers` and `unresolved_requirements`, never host-only checks.
If source edits are complete, report `status=completed` even before host validation.
"""


def _repair_prompt(
    feedback: dict[str, Any], iteration: int, *, phase: str = "design_game_logic"
) -> str:
    return f"""Repair the Unity project using the host validator evidence below.

Repair iteration: {iteration}
Validation phase: {phase}
Evidence:
{json.dumps(feedback, ensure_ascii=False, indent=2)}

Return an updated `visual_objects` array for any new visible object categories introduced by
this repair. Preserve IDs and scene name prefixes for objects already implemented; the host
uses these IDs to request artwork after Unity validation.
Return an updated `sound_events` array for newly implemented audible transitions. Preserve
previously reported sound IDs and cues, and keep each cue wired to its runtime transition.

Read the referenced source definitions before editing. Fix root causes across files and bindings,
not only the first compiler line. Do not weaken tests or alter immutable generated design/manifest
JSON. Keep already working requested features intact. Do not create or modify `.meta` files or
hand-edit `Bootstrap.unity`; let the host assembler regenerate bindings. Do not create or modify
`.asmdef`/`.asmref` files and do not add dynamic `Assembly.Load` workarounds. Keep one public
MonoBehaviour per filename-matched `.cs` file and preserve every existing generated module ID.
For `UNITY_MODULE_DEPENDENCY_INVALID` or a missing service in `OnInitialize`, inspect both
modules and their IDs. Put the provider before its consumer in `GameTemplateConfig.asset`
`selectedModules` without removing either module; then let the host rerun Unity validation.
Every generated module class must be public and individually serializable; split any file that
contains multiple `[GeneratedGameModule]` classes instead of keeping an internal class bundle.
When the phase is `validate_game`, starts with `feature_checklist`, or is `final_validation`,
preserve generated and applied image/audio
files, their binding IDs, and asset manifests. Fix gameplay source, scene assembly, UI bindings,
initialization, and state transitions without replacing validated assets or reverting the game to
the copied genre prototype.
When the phase starts with `feature_checklist`, treat every failed checklist assertion as an
acceptance criterion only if it is compatible with the user's explicit attack delivery and
exclusions. A generic projectile checklist must never turn an explicitly orbiting melee sword
into a player projectile attack. Read the referenced production type and checklist source, then implement
the missing observable runtime behavior or compatible public contract in production code.
Never edit, delete, disable, or weaken the checklist test itself.
If a runtime exception reports a null route, spawn point, module, or HUD object, repair the source
by reacquiring that object at runtime and by adding an explicit null/empty guard; do not hide the
exception by disabling the wave, combat, or UI system.
If a runtime exception reports a missing component, replace null-coalescing component lookup with
an explicit Unity-aware null check and ensure the component is present on every object path that
can invoke the method.
If `runtime.hazard_damage` fails after a route or checkpoint transition, trace all controllers
that can move or respawn the player before the hazard's damage callback. Scope timed or rising
hazard checks to their own zone and restore that zone's state on respawn. Confirm the ordinary
hazard changes the authoritative player health; do not bypass contact damage or change the host
smoke test to hide the failure.
If `runtime.ui_quality` fails, fix every panel in `ui_opacity_corrections` in one edit.
Set each named panel Image's
color alpha to exactly 1.0; values such as 0.95 or 0.99 are insufficient for the
opaque HUD contract. Keep the backing and verify its final color after helpers and
artwork binders run, including panels initially inactive for level-ups or boss fights.
Do not relax the validator or hide the panel to avoid the check.
Inspect the failing panel's actual RectTransform geometry before moving labels. Confirm
that helper arguments use position plus width/height rather
than position plus far corner; correct oversized or off-screen panels first. Then place
content inside the reported safe rectangle with several screen pixels of spare padding
at every edge. Fix *every* item in `ui_layout_corrections` in one edit; the host lists
all currently overflowing HUD children, not just the first. For an item that fits inside
the safe rectangle, move it by the reported screen-pixel correction (plus padding);
for one wider or taller than the safe rectangle, reduce/reflow its RectTransform or split
the HUD into distinct panels. With a Screen Space Overlay Canvas, convert screen pixels
to a direct child's local `anchoredPosition` using `Canvas.scaleFactor`. Do not enlarge
one panel to chase a child if that moves the panel outside the screen or into another HUD.
Fix every `text_overflow_modes` item even if its rectangle is already inside the safe area.
Set horizontal and vertical modes to `Wrap` or `Truncate` as appropriate, and ensure
required values remain fully readable. Keep each Text font size at least 14px; reflow
or split panels instead of making the type too small.
Put live text, bars, and buttons under the intended decorated panel's
RectTransform; if they are siblings, verify that their actual screen rectangles overlap
that panel. A `HudArt_` decoration must never make the entire Canvas its content panel.
Check anchors, pivot, `sizeDelta`, and CanvasScaler at the failing screen resolution.
Do not solve a 1-pixel overflow by changing text clipping alone.
If `runtime.survivor_player_identity`, `runtime.survivor_player_binding`, or
`runtime.survivor_movement` fails, inspect all Player creation paths and Rigidbody2D bindings.
Keep one active scene Player, bind TopDownMovementModule, camera, health, enemy targets, and UI
to its live transform/body, and remove competing movement logic. Confirm the test input reaches
that exact body; changing only movement speed or timeout cannot repair a different-body binding.
If validation reports that a selected action or upgrade changed no observable state, inspect module
initialization order and reacquire late-bound dependencies when the action executes. Ensure every
selectable option ID maps to a real state mutation, and keep one authoritative owner for the state
instead of updating a parallel controller that the UI or validator does not observe.
For `runtime.survivor_upgrade_contract` or `runtime.survivor_upgrade_effect`, inspect the
selected `UpgradeDefinition.observableStatId` and `expectedStatChange`. The live gameplay
component owning that value must implement `IGameplayStatSource` and return a finite number
for the same stat ID before and after selection. Set the stat ID on blueprint-imported options
as well as options added in code. Read `stat_before`, `stat_after`, and `expected_change` in
the smoke log. If the value did not move as declared, repair the actual effect application,
its runtime binding, or its `Selected` subscription. Do not replace it with a UI/acquired
counter or change the host validator to accept an unrelated state change.
If the tower-defense smoke test reports `runtime.tower_build_visibility`, position every build
point inside the camera view and set its SpriteRenderer sorting order above the background.
If it reports `runtime.tower_build_clickability` or `runtime.tower_build_input`, check the
build-point Collider2D, UI raycast coverage, EventSystem/input module, button listener, selected
point state, and gold deduction as one end-to-end pointer flow.
If it reports `runtime.tower_build_menu_visibility` or `runtime.tower_build_menu_clickability`,
inspect the actual button RectTransform corners and UI raycast results at its screen center.
For a bottom-right panel, align its pivot with `(1, 0)` and inset it from the screen edges;
do not solve an off-screen button by invoking its callback directly.
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
the required structured report. If source edits are complete and only host Unity validation is
pending, report `status=completed` and list that check in `recommended_validation`.
Set `host_validation_pending=true` for host-owned Unity checks and leave
`implementation_blockers` empty when source implementation is complete.
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
    """Keep a root failure stable when edits shift line numbers or wrapper messages."""

    log = outcome.unity_log
    issue_codes = sorted({item["code"] for item in outcome.issues})
    runtime = re.search(r"UNITY_RUNTIME_SMOKE_FAILED:\s*([\w.]+)", log)
    if runtime:
        payload = {"issues": issue_codes, "runtime_transition": runtime.group(1)}
        if runtime.group(1) == "runtime.ui_quality":
            ui_content = _ui_layout_overflow(log)
            if ui_content is not None:
                payload["ui_target"] = [ui_content[0], ui_content[1]]
            else:
                ui_panel = re.search(r"HUD panel '([^']+)'", log)
                if ui_panel:
                    payload["ui_target"] = ui_panel.group(1)
    else:
        compiler = re.findall(r"error (CS\d+):\s*([^\r\n]+)", log)
        if compiler:
            payload = {"issues": issue_codes, "compiler": sorted(set(compiler))[:5]}
        else:
            validation = re.findall(r"VALIDATION_FAIL:([\w.]+)", log)
            if validation:
                payload = {"issues": issue_codes, "validation": sorted(set(validation))[:5]}
            else:
                exception = re.search(r"(?m)^([\w.]+Exception):", log)
                method = re.search(r"executeMethod method ([\w.]+) threw exception", log)
                if exception:
                    payload = {
                        "issues": issue_codes,
                        "exception": exception.group(1),
                        "method": method.group(1) if method else "",
                    }
                else:
                    payload = {
                        "issues": issue_codes,
                        "diagnostics": _signature_diagnostics(log)[:5],
                    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _ui_layout_violations(
    log: str,
) -> list[tuple[str, str, tuple[float, float, float, float], tuple[float, float, float, float]]]:
    """Collect every reported HUD content rectangle, including later failures."""

    pattern = re.compile(
        r"HUD content '([^']+)' escapes decorated panel '([^']+)' "
        r"safe area \(([^)]+)\); content bounds \(([^)]+)\)",
    )

    def bounds(raw: str) -> tuple[float, float, float, float] | None:
        values = {
            name: float(value)
            for name, value in re.findall(r"(x|y|width|height):\s*(-?\d+(?:\.\d+)?)", raw)
        }
        if len(values) != 4:
            return None
        return (
            values["x"],
            values["y"],
            values["x"] + values["width"],
            values["y"] + values["height"],
        )

    violations = []
    for match in pattern.finditer(log):
        safe = bounds(match.group(3))
        content = bounds(match.group(4))
        if safe is not None and content is not None:
            violations.append((match.group(2), match.group(1), safe, content))
    return violations


def _ui_layout_repair_guidance(log: str) -> list[dict[str, Any]]:
    """Give the repair agent actionable screen-space deltas for all HUD violations."""

    guidance = []
    for panel, content_name, safe, content in _ui_layout_violations(log)[:24]:
        left = max(0.0, safe[0] - content[0])
        bottom = max(0.0, safe[1] - content[1])
        right = max(0.0, content[2] - safe[2])
        top = max(0.0, content[3] - safe[3])
        safe_width = safe[2] - safe[0]
        safe_height = safe[3] - safe[1]
        width = content[2] - content[0]
        height = content[3] - content[1]
        guidance.append(
            {
                "panel": panel,
                "content": content_name,
                "overflow_screen_px": {
                    "left": round(left, 1),
                    "right": round(right, 1),
                    "bottom": round(bottom, 1),
                    "top": round(top, 1),
                },
                "move_screen_px_with_8px_padding": {
                    "x": round(left + 8 if left else -(right + 8) if right else 0, 1),
                    "y": round(bottom + 8 if bottom else -(top + 8) if top else 0, 1),
                }
                if width <= safe_width - 16 and height <= safe_height - 16
                else None,
                "maximum_content_size_screen_px_with_8px_padding": {
                    "width": round(max(0.0, safe_width - 16), 1),
                    "height": round(max(0.0, safe_height - 16), 1),
                },
            }
        )
    for match in re.finditer(
        r"HUD text '([^']+)' in decorated panel '([^']+)' uses overflow modes: "
        r"horizontal=(\w+), vertical=(\w+)",
        log,
    ):
        guidance.append(
            {
                "panel": match.group(2),
                "content": match.group(1),
                "text_overflow_modes": {
                    "horizontal": match.group(3),
                    "vertical": match.group(4),
                },
                "required_action": "Use Wrap or Truncate and keep text readable at 14px or larger",
            }
        )
    return guidance


def _ui_layout_overflow(log: str) -> tuple[str, str, float] | None:
    """Measure the worst HUD overflow rather than only the first diagnostic."""

    violations = _ui_layout_violations(log)
    if not violations:
        return None
    panel, content_name, safe, content = max(
        violations,
        key=lambda item: sum(
            (
                max(0.0, item[2][0] - item[3][0]),
                max(0.0, item[2][1] - item[3][1]),
                max(0.0, item[3][2] - item[2][2]),
                max(0.0, item[3][3] - item[2][3]),
            )
        ),
    )
    overflow = sum(
        (
            max(0.0, safe[0] - content[0]),
            max(0.0, safe[1] - content[1]),
            max(0.0, content[2] - safe[2]),
            max(0.0, content[3] - safe[3]),
        )
    )
    return panel, content_name, overflow


def _ui_opacity_violations(log: str) -> list[dict[str, str | float | None]]:
    violations: list[dict[str, str | float | None]] = []
    for match in re.finditer(
        r"HUD panel '([^']+)' must have an opaque backing"
        r"(?: \(alpha=([0-9.]+), required=1\))?",
        log,
    ):
        violations.append(
            {
                "panel": match.group(1),
                "alpha": float(match.group(2)) if match.group(2) else None,
                "required_alpha": 1.0,
            }
        )
    return violations


@dataclass(frozen=True)
class _UiQualityMetrics:
    opacity_count: int
    geometry_count: int
    overflow_pixels: float
    text_overflow_count: int
    undersized_text_count: int


def _ui_quality_metrics(log: str) -> _UiQualityMetrics | None:
    if "UNITY_RUNTIME_SMOKE_FAILED: runtime.ui_quality:" not in log:
        return None
    geometry = _ui_layout_violations(log)
    overflow_pixels = sum(
        max(0.0, safe[0] - content[0])
        + max(0.0, safe[1] - content[1])
        + max(0.0, content[2] - safe[2])
        + max(0.0, content[3] - safe[3])
        for _, _, safe, content in geometry
    )
    old_text_modes = re.findall(r"Text overflow modes: horizontal=(\w+), vertical=(\w+)", log)
    new_text_modes = re.findall(
        r"HUD text '[^']+' in decorated panel '[^']+' uses overflow modes: "
        r"horizontal=(\w+), vertical=(\w+)",
        log,
    )
    text_overflow_count = sum(
        horizontal == "Overflow" or vertical == "Overflow"
        for horizontal, vertical in (*old_text_modes, *new_text_modes)
    )
    return _UiQualityMetrics(
        opacity_count=len(_ui_opacity_violations(log)),
        geometry_count=len(geometry),
        overflow_pixels=overflow_pixels,
        text_overflow_count=text_overflow_count,
        undersized_text_count=len(re.findall(r"text '[^']+' is too small \(\d+px\)", log)),
    )


def _ui_quality_improved(baseline: _UiQualityMetrics, candidate: _UiQualityMetrics) -> bool:
    return (
        candidate.opacity_count <= baseline.opacity_count
        and candidate.geometry_count <= baseline.geometry_count
        and candidate.overflow_pixels <= baseline.overflow_pixels + 0.5
        and candidate.text_overflow_count <= baseline.text_overflow_count
        and candidate.undersized_text_count <= baseline.undersized_text_count
        and (
            candidate.opacity_count < baseline.opacity_count
            or candidate.geometry_count < baseline.geometry_count
            or candidate.overflow_pixels < baseline.overflow_pixels - 0.5
            or candidate.text_overflow_count < baseline.text_overflow_count
            or candidate.undersized_text_count < baseline.undersized_text_count
        )
    )


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
                "ArgumentNullException:",
                "Parameter name:",
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
    "UNITY_UI_QUALITY_OK",
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
    baseline_ui = _ui_quality_metrics(baseline.unity_log)
    candidate_ui = _ui_quality_metrics(candidate.unity_log)
    if baseline_ui is not None and candidate_ui is not None:
        if candidate_ui.opacity_count > baseline_ui.opacity_count:
            return True
        if candidate_ui.undersized_text_count > baseline_ui.undersized_text_count:
            return True
        if _ui_quality_improved(baseline_ui, candidate_ui):
            return False
        # At the same UI stage, a changed classifier target is not evidence that
        # fewer HUD violations became a more severe Unity failure.
        return (
            candidate_ui.geometry_count >= baseline_ui.geometry_count
            and candidate_ui.overflow_pixels > baseline_ui.overflow_pixels + 0.5
            and candidate_ui.text_overflow_count >= baseline_ui.text_overflow_count
        )
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
