"""VLM-driven visual review with bounded Unity source repair."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from PIL import Image

from game_pipeline.feature_checklist_validation import (
    ChecklistResult,
    FeatureChecklistRepairAI,
    FeatureChecklistWorkflow,
)
from game_pipeline.unity_project_validator import UnityProjectValidator
from mainflow.contracts import (
    ArtifactReference,
    GameLogicDraft,
    LogicAnalysis,
    ParsedRequest,
    VisualValidationAttempt,
    VisualValidationResult,
)
from MCP.llm_config import LLMSettings
from MCP.llm_providers import create_llm_provider
from MCP.llm_types import LLMConversationMessage

VISUAL_VALIDATION_ENV = "MAINFLOW_VISUAL_VALIDATION"
VISUAL_ATTEMPTS_ENV = "MAINFLOW_VISUAL_VALIDATION_ATTEMPTS"
VISUAL_PROVIDER_ENV = "LLM_VISUAL_VALIDATION_PROVIDER"
VISUAL_MODEL_ENV = "LLM_VISUAL_VALIDATION_MODEL"
VISUAL_MAX_TOKENS_ENV = "LLM_VISUAL_VALIDATION_MAX_TOKENS"
VISUAL_REVIEW_ATTEMPTS_ENV = "LLM_VISUAL_VALIDATION_RESPONSE_ATTEMPTS"
DEFAULT_VLM_MODEL = "qwen3-vl-4b-instruct-q4-k-m"
MAX_VISUAL_ATTEMPTS = 3
REQUIRED_VISUAL_IDS = frozenset(f"VC{index:02d}" for index in range(1, 9))
VISUAL_CAPTURE_TEST = "TeamIdle.GameTemplate.VisualTests.VisualCaptureTests"
VISUAL_PROJECT_ROOT = Path("game/unity_project")


def visual_validation_enabled(value: str | None = None) -> bool:
    """Resolve the explicit visual-validation mode without surprising existing runs."""

    normalized = value if value is not None else os.environ.get(VISUAL_VALIDATION_ENV, "0")
    normalized = normalized.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    raise ValueError(f"{VISUAL_VALIDATION_ENV} must be enabled or disabled")


def visual_attempt_limit(value: str | None = None) -> int:
    attempts = int(value if value is not None else os.environ.get(VISUAL_ATTEMPTS_ENV, "3"))
    if not 1 <= attempts <= MAX_VISUAL_ATTEMPTS:
        raise ValueError(f"{VISUAL_ATTEMPTS_ENV} must be between 1 and 3")
    return attempts


def load_visual_checklist(path: Path) -> tuple[str, tuple[str, ...]]:
    text = path.read_text(encoding="utf-8")
    ids = tuple(dict.fromkeys(re.findall(r"\|\s*(VC\d{2})\s*\|", text)))
    if not ids:
        raise ValueError(f"Visual checklist contains no VC identifiers: {path}")
    return text, ids


def _data_url(content: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(content).decode("ascii")


def _strict_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE)
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise TypeError("VLM response must be one JSON object")
    return cast(dict[str, Any], payload)


class VisualTargetGenerator(Protocol):
    """Boundary implemented by the workflow layer, independent of asset backends."""

    def generate(self, request: ParsedRequest, logic: LogicAnalysis) -> bytes:
        """Return one comparison-only gameplay target image."""


def build_visual_target_prompt(request: ParsedRequest, logic: LogicAnalysis) -> str:
    """Build the comparison-image prompt without selecting an image backend."""

    features = ", ".join(item["name"] for item in logic["features"])
    return (
        "A polished but feasible 2D Unity gameplay screenshot, not key art or a poster. "
        f"Genre: {request['genre']}; viewpoint: {request['viewpoint']}; "
        f"art style: {request['image_style']}; mood: {request['mood_style']}. "
        f"User request: {request['condition']}. Visible gameplay features: {features}. "
        "Show the player, traversable play space, threats or objectives, and a readable minimal "
        "HUD. Use a 16:9 composition, no logos, no mock-device frame, no explanatory text."
    )


class VisualVLMReviewer:
    """Compare target/current screenshots through the common LLM provider adapter."""

    def review(
        self,
        *,
        target: bytes,
        current: bytes,
        checklist: str,
        checklist_ids: tuple[str, ...],
        request: ParsedRequest,
        inventory: list[str],
    ) -> tuple[dict[str, Any], str]:
        provider_name = os.environ.get(VISUAL_PROVIDER_ENV, "local")
        if provider_name.strip().lower() in {"vast", "vastai", "vast.ai", "vllm"}:
            from VastAI.settings import load_vastai_settings

            remote = load_vastai_settings("vlm")
            settings = LLMSettings(
                provider="vastai",
                model=remote.model,
                api_key=remote.api_key,
                base_url=remote.base_url,
                timeout_seconds=remote.timeout_seconds,
            )
        else:
            model = os.environ.get(VISUAL_MODEL_ENV, DEFAULT_VLM_MODEL)
            settings = LLMSettings.from_environment(
                node_name="visual_validation",
                provider=provider_name,
                model=model,
            )
        if settings.provider not in {"local", "openai", "vastai"}:
            raise ValueError(
                "Visual image inputs currently require a local or OpenAI-compatible provider"
            )
        max_tokens = int(os.environ.get(VISUAL_MAX_TOKENS_ENV, "768"))
        if not 256 <= max_tokens <= 2048:
            raise ValueError(f"{VISUAL_MAX_TOKENS_ENV} must be between 256 and 2048")

        async def call() -> str:
            provider = create_llm_provider(settings)
            try:
                response = await provider.complete(
                    [
                        LLMConversationMessage(
                            role="user",
                            content=[
                                {
                                    "type": "text",
                                    "text": self._prompt(
                                        checklist, checklist_ids, request, inventory
                                    ),
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": _data_url(target), "detail": "high"},
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": _data_url(current), "detail": "high"},
                                },
                            ],
                        )
                    ],
                    [],
                    system_prompt=(
                        "You are a strict 2D game visual QA lead. The first image is the intended "
                        "target and the second is the current Unity capture. Judge only visible "
                        "evidence and return strict JSON without markdown."
                    ),
                    temperature=0.0,
                    require_tool=False,
                    max_tokens=max_tokens,
                )
                return response.text
            finally:
                await provider.aclose()

        response_attempts = int(os.environ.get(VISUAL_REVIEW_ATTEMPTS_ENV, "2"))
        if not 1 <= response_attempts <= 3:
            raise ValueError(f"{VISUAL_REVIEW_ATTEMPTS_ENV} must be between 1 and 3")
        last_error: ValueError | None = None
        for _ in range(response_attempts):
            try:
                payload = self._validate(
                    self._normalize(_strict_json(asyncio.run(call()))), checklist_ids
                )
                return payload, settings.model
            except ValueError as error:
                last_error = error
        raise ValueError(
            f"Visual review returned an invalid checklist after {response_attempts} attempts: "
            f"{last_error}"
        )

    @staticmethod
    def _prompt(
        checklist: str,
        checklist_ids: tuple[str, ...],
        request: ParsedRequest,
        inventory: list[str],
    ) -> str:
        return f"""Compare image 1 (target) with image 2 (current Unity game).

REQUEST:
{json.dumps(request, ensure_ascii=False, default=str)}

VISUAL CHECKLIST:
{checklist}

EDITABLE PROJECT FILE INVENTORY (hints only; do not claim you read contents):
{json.dumps(inventory[:600], ensure_ascii=False)}

Keep every message under 12 words and return at most 3 findings. Return exactly this compact JSON
shape and include every criterion ID {list(checklist_ids)}:
{{
  "status": "passed|needs_revision",
  "score": 0,
  "summary": "short comparison",
  "results": [
    {{"id": "VC01", "s": "passed|failed|unverifiable", "m": "visible evidence"}}
  ],
  "findings": [
    {{"sev": "warning|error", "id": "VC01", "problem": "problem", "fix": "change", "files": ["path from inventory"]}}
  ]
}}

Passing requires score >= 80, no error finding, and all required visible criteria passing.
Do not fail hidden runtime behavior that a still image cannot prove; mark it unverifiable.
"""

    @staticmethod
    def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
        """Expand the VLM's compact wire JSON into the stable workflow contract."""

        if "results" not in payload:
            return payload
        compact_results = payload.get("results")
        compact_findings = payload.get("findings")
        if not isinstance(compact_results, list) or not isinstance(compact_findings, list):
            raise TypeError("Compact visual response requires results and findings lists")
        results = []
        for item in compact_results:
            if not isinstance(item, dict):
                raise TypeError("Compact checklist entries must be objects")
            message = str(item.get("m", "")).strip()
            results.append(
                {
                    "criterion_id": item.get("id"),
                    "status": VisualVLMReviewer._enum_alias(
                        item.get("s"),
                        {
                            "pass": "passed",
                            "ok": "passed",
                            "fail": "failed",
                            "unknown": "unverifiable",
                            "not_visible": "unverifiable",
                        },
                    ),
                    "message": message,
                    "evidence": [message] if message else [],
                }
            )
        findings = []
        for item in compact_findings:
            if not isinstance(item, dict):
                raise TypeError("Compact finding entries must be objects")
            findings.append(
                {
                    "severity": VisualVLMReviewer._enum_alias(
                        item.get("sev"),
                        {"warn": "warning", "critical": "error", "failed": "error"},
                    ),
                    "criterion_id": item.get("id"),
                    "message": str(item.get("problem", "")).strip(),
                    "recommendation": str(item.get("fix", "")).strip(),
                    "suggested_files": item.get("files") or [],
                }
            )
        return {
            "status": VisualVLMReviewer._enum_alias(
                payload.get("status"),
                {
                    "pass": "passed",
                    "ok": "passed",
                    "fail": "needs_revision",
                    "failed": "needs_revision",
                    "revision": "needs_revision",
                },
            ),
            "score": payload.get("score"),
            "summary": str(payload.get("summary", "")).strip(),
            "checklist_results": results,
            "findings": findings,
        }

    @staticmethod
    def _enum_alias(value: Any, aliases: dict[str, str]) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
        return aliases.get(normalized, normalized)

    @staticmethod
    def _validate(payload: dict[str, Any], checklist_ids: tuple[str, ...]) -> dict[str, Any]:
        status = payload.get("status")
        score = payload.get("score")
        results = payload.get("checklist_results")
        findings = payload.get("findings")
        if status not in {"passed", "needs_revision"}:
            raise ValueError("Visual review status must be passed or needs_revision")
        if not isinstance(score, (int, float)) or not 0 <= float(score) <= 100:
            raise ValueError("Visual review score must be between 0 and 100")
        if not isinstance(results, list) or not isinstance(findings, list):
            raise TypeError("Visual review requires checklist_results and findings lists")
        if len(findings) > 3:
            raise ValueError("Visual review may return at most three findings")
        if any(
            not isinstance(item, dict)
            or item.get("status") not in {"passed", "failed", "unverifiable"}
            for item in results
        ):
            raise ValueError("Visual checklist result contains an unsupported status")
        if any(
            not isinstance(item, dict) or item.get("severity") not in {"warning", "error"}
            for item in findings
        ):
            raise ValueError("Visual finding contains an unsupported severity")
        returned_ids = [item.get("criterion_id") for item in results if isinstance(item, dict)]
        if len(returned_ids) != len(checklist_ids) or set(returned_ids) != set(checklist_ids):
            raise ValueError("Visual review must return every checklist criterion exactly once")
        has_error = any(
            isinstance(item, dict) and item.get("severity") == "error" for item in findings
        )
        failed_required = any(
            isinstance(item, dict)
            and item.get("criterion_id") in REQUIRED_VISUAL_IDS
            and item.get("status") != "passed"
            for item in results
        )
        if status == "passed" and (float(score) < 80 or has_error or failed_required):
            raise ValueError(
                "Visual review cannot pass below score 80, with an error, or with an unmet "
                "required criterion"
            )
        return payload


class UnityVisualCapture:
    """Run the host-owned PlayMode capture test with graphics enabled."""

    def __init__(self, editor: Path, timeout_seconds: int) -> None:
        self.editor = editor
        self.timeout_seconds = timeout_seconds

    def capture(self, project_root: Path) -> tuple[bytes, str]:
        temporary = Path(tempfile.mkdtemp(prefix="mainflow-visual-capture-"))
        try:
            image_path = temporary / "gameplay.ppm"
            results_path = temporary / "results.xml"
            log_path = temporary / "capture.log"
            environment = os.environ.copy()
            environment["MAINFLOW_VISUAL_CAPTURE_PATH"] = str(image_path)
            completed = subprocess.run(
                [
                    str(self.editor),
                    "-batchmode",
                    "-projectPath",
                    str(project_root),
                    "-runTests",
                    "-testPlatform",
                    "PlayMode",
                    "-testFilter",
                    VISUAL_CAPTURE_TEST,
                    "-testResults",
                    str(results_path),
                    "-logFile",
                    str(log_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                env=environment,
            )
            log = (completed.stdout or "") + (completed.stderr or "")
            if log_path.is_file():
                log += log_path.read_text(encoding="utf-8", errors="replace")
            if completed.returncode != 0 or not image_path.is_file():
                raise RuntimeError(
                    "Unity visual capture failed "
                    f"(exit={completed.returncode}); run without -nographics and inspect: {log[-4000:]}"
                )
            with Image.open(image_path) as image:
                output = io.BytesIO()
                image.convert("RGB").save(output, format="PNG", optimize=True)
            return output.getvalue(), log
        finally:
            # Unity can retain its log handle briefly after the process exits on Windows.
            shutil.rmtree(temporary, ignore_errors=True)


@dataclass(frozen=True)
class VisualRepairOutcome:
    modified_files: list[str]
    compile_passed: bool
    feature_checklist_passed: bool
    log: str


class VisualValidationWorkflow:
    """Generate, compare, repair, and revalidate at most three visual attempts."""

    def __init__(
        self,
        *,
        editor: Path,
        timeout_seconds: int,
        checklist_path: Path,
        source_docs: Path,
        attempts: int,
        target_generator: VisualTargetGenerator,
        reviewer_factory: Callable[[], VisualVLMReviewer] = VisualVLMReviewer,
        capture: UnityVisualCapture | None = None,
        repair_factory: Callable[[], FeatureChecklistRepairAI] = (
            FeatureChecklistRepairAI.from_environment
        ),
    ) -> None:
        if not 1 <= attempts <= MAX_VISUAL_ATTEMPTS:
            raise ValueError("Visual validation attempts must be between 1 and 3")
        self.editor = editor
        self.timeout_seconds = timeout_seconds
        self.checklist_path = checklist_path
        self.source_docs = source_docs
        self.attempts = attempts
        self.target_generator = target_generator
        self.reviewer_factory = reviewer_factory
        self.capture = capture or UnityVisualCapture(editor, timeout_seconds)
        self.repair_factory = repair_factory

    def run(
        self,
        *,
        project_root: Path,
        workspace_root: Path,
        request: ParsedRequest,
        logic: LogicAnalysis,
        draft: GameLogicDraft,
        record_image: Callable[[str, bytes], ArtifactReference],
    ) -> VisualValidationResult:
        checklist, checklist_ids = load_visual_checklist(self.checklist_path)
        inventory = self._inventory(project_root)
        target = self.target_generator.generate(request, logic)
        target_reference = record_image("visual/target.png", target)
        attempts: list[VisualValidationAttempt] = []
        model = "none"

        initial = self._hard_validation(project_root, workspace_root, draft, request)
        if not initial.compile_passed or not initial.feature_checklist_passed:
            return {
                "report_version": "1.0.0",
                "contract_version": request["contract_version"],
                "mode": "enabled",
                "status": "failed",
                "model": model,
                "max_attempts": self.attempts,
                "attempts": [],
                "target_image": target_reference,
                "summary": "Visual capture was blocked because compile or feature checks failed.",
            }

        for attempt_number in range(1, self.attempts + 1):
            current, _ = self.capture.capture(project_root)
            current_reference = record_image(f"visual/attempt_{attempt_number}.png", current)
            review, model = self.reviewer_factory().review(
                target=target,
                current=current,
                checklist=checklist,
                checklist_ids=checklist_ids,
                request=request,
                inventory=inventory,
            )
            attempt: VisualValidationAttempt = {
                "attempt": attempt_number,
                "status": review["status"],
                "score": float(review["score"]),
                "summary": str(review.get("summary", "")),
                "screenshot": current_reference,
                "checklist_results": review["checklist_results"],
                "findings": review["findings"],
                "modified_files": [],
                "compile_passed": None,
                "feature_checklist_passed": None,
            }
            attempts.append(attempt)
            if review["status"] == "passed":
                return {
                    "report_version": "1.0.0",
                    "contract_version": request["contract_version"],
                    "mode": "enabled",
                    "status": "passed",
                    "model": model,
                    "max_attempts": self.attempts,
                    "attempts": attempts,
                    "target_image": target_reference,
                    "summary": f"Visual validation passed on attempt {attempt_number}.",
                }
            if attempt_number == self.attempts:
                break
            try:
                repair = self._repair(project_root, workspace_root, draft, request, review)
            except Exception as error:  # noqa: BLE001 - retain the completed visual evidence
                attempt["status"] = "failed"
                attempt["summary"] += f" Repair failed: {type(error).__name__}: {error}"
                break
            attempt["modified_files"] = repair.modified_files
            attempt["compile_passed"] = repair.compile_passed
            attempt["feature_checklist_passed"] = repair.feature_checklist_passed

        return {
            "report_version": "1.0.0",
            "contract_version": request["contract_version"],
            "mode": "enabled",
            "status": "failed",
            "model": model,
            "max_attempts": self.attempts,
            "attempts": attempts,
            "target_image": target_reference,
            "summary": f"Visual validation did not pass within {self.attempts} attempts.",
        }

    def _repair(
        self,
        project_root: Path,
        workspace_root: Path,
        draft: GameLogicDraft,
        request: ParsedRequest,
        review: dict[str, Any],
    ) -> VisualRepairOutcome:
        snapshots = {
            path: (project_root / path).read_text(encoding="utf-8")
            for path in self._inventory(project_root)
        }
        failures = [
            ChecklistResult(
                feature_id=str(item.get("criterion_id", "VISUAL")),
                feature_name="시각 검증",
                status="failed",
                message=(
                    f"{item.get('message', '')}; recommendation={item.get('recommendation', '')}"
                    f"; suggested_files={item.get('suggested_files', [])}"
                ),
                test_name="visual_validation",
            )
            for item in review.get("findings", [])
            if isinstance(item, dict)
        ]
        if not failures:
            failures.append(
                ChecklistResult(
                    "VISUAL",
                    "시각 검증",
                    "failed",
                    str(review.get("summary", "Visual target mismatch")),
                    "visual_validation",
                )
            )
        repair_ai = self.repair_factory()
        plan = repair_ai.repair(
            project_root,
            failures,
            json.dumps(review, ensure_ascii=False),
        )
        validation = self._hard_validation(project_root, workspace_root, draft, request)
        if not validation.compile_passed or not validation.feature_checklist_passed:
            for path in plan.target_files:
                previous = snapshots.get(path)
                if previous is not None:
                    (project_root / path).write_text(previous, encoding="utf-8")
        return VisualRepairOutcome(
            modified_files=list(plan.target_files),
            compile_passed=validation.compile_passed,
            feature_checklist_passed=validation.feature_checklist_passed,
            log=validation.log,
        )

    def _hard_validation(
        self,
        project_root: Path,
        workspace_root: Path,
        draft: GameLogicDraft,
        request: ParsedRequest,
    ) -> VisualRepairOutcome:
        validator = UnityProjectValidator(
            mode="required",
            unity_editor=self.editor,
            timeout_seconds=self.timeout_seconds,
        )
        compile_outcome = validator.validate(project_root, draft, request)
        if compile_outcome.status != "passed":
            return VisualRepairOutcome([], False, False, compile_outcome.unity_log)
        checklist = FeatureChecklistWorkflow(
            unity_editor=self.editor,
            timeout_seconds=self.timeout_seconds,
            max_retries=0,
        ).run(
            project_root=project_root,
            workspace_root=workspace_root,
            source_root=self.source_docs,
            compile_validation=lambda root: validator.validate(root, draft, request),
        )
        return VisualRepairOutcome(
            [],
            True,
            checklist.status == "passed",
            compile_outcome.unity_log + checklist.log,
        )

    @staticmethod
    def _inventory(root: Path) -> list[str]:
        allowed = {".cs", ".json", ".asset", ".unity"}
        protected = ("Assets/Tests/", "Packages/", "ProjectSettings/")
        files: list[str] = []
        for path in sorted((root / "Assets").rglob("*")):
            if not path.is_file() or path.suffix.lower() not in allowed:
                continue
            relative = path.relative_to(root).as_posix()
            if any(relative.startswith(prefix) for prefix in protected):
                continue
            files.append(relative)
            if len(files) == 600:
                break
        return files
