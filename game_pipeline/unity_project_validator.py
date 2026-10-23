"""Validate generated Unity projects without depending on generated assets."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

from game_pipeline.design_v2 import validate_design_v2
from mainflow.contracts import (
    CONTRACT_VERSION,
    DesignV2Bundle,
    GameLogicDraft,
    ParsedRequest,
    ValidationCheckResult,
    ValidationIssue,
    ValidationStatus,
)

UnityValidationMode = Literal["auto", "required", "static"]


@dataclass
class UnityValidationOutcome:
    """Machine-readable checks and issues produced by one validation run."""

    checks: list[ValidationCheckResult] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    unity_log: str = ""

    @property
    def status(self) -> ValidationStatus:
        has_error = any(issue["severity"] == "error" for issue in self.issues)
        has_failed_check = any(not check["passed"] for check in self.checks)
        return "failed" if has_error or has_failed_check else "passed"


class UnityProjectValidator:
    """Run deterministic structure checks and optional Unity batch validation."""

    REQUIRED_JSON_PATHS: ClassVar[dict[str, Path]] = {
        "design": Path("Assets/GameTemplate/Generated/GameLogicDesign.json"),
        "implementation_plan": Path("Assets/GameTemplate/Generated/GameImplementationPlan.json"),
        "implementation_tasks": Path("Assets/GameTemplate/Generated/ImplementationTasks.json"),
        "game_blueprint": Path("Assets/GameTemplate/Generated/GameBlueprint.json"),
        "game_design": Path("Assets/GameTemplate/Generated/Design/game_design.json"),
        "system_design": Path("Assets/GameTemplate/Generated/Design/system_design.json"),
        "content_plan": Path("Assets/GameTemplate/Generated/Design/content_plan.json"),
        "level_plan": Path("Assets/GameTemplate/Generated/Design/level_plan.json"),
        "balance_plan": Path("Assets/GameTemplate/Generated/Design/balance_plan.json"),
        "presentation_plan": Path("Assets/GameTemplate/Generated/Design/presentation_plan.json"),
        "validation_plan": Path("Assets/GameTemplate/Generated/Design/validation_plan.json"),
        "manifest": Path("GenerationManifest.json"),
        "image_request": Path(
            "Assets/GameTemplate/Generated/AssetRequests/image_asset_request.json"
        ),
        "sound_request": Path(
            "Assets/GameTemplate/Generated/AssetRequests/sound_asset_request.json"
        ),
        "packages": Path("Packages/manifest.json"),
    }
    REQUIRED_FILE_PATHS: ClassVar[dict[str, Path]] = {
        "project_version": Path("ProjectSettings/ProjectVersion.txt"),
        "config": Path("Assets/GameTemplate/Generated/GameTemplateConfig.asset"),
        "builder": Path("Assets/GameTemplate/Editor/TemplateProjectBuilder.cs"),
        "module_catalog": Path("Assets/GameTemplate/Editor/ModuleComponentCatalog.cs"),
        "scene_assembler": Path("Assets/GameTemplate/Editor/PrefabSceneAssembler.cs"),
        "blueprint_loader": Path("Assets/GameTemplate/Editor/GameBlueprint.cs"),
        "level_plan_loader": Path("Assets/GameTemplate/Editor/LevelPlan.cs"),
        "gameplay_plan_loaders": Path("Assets/GameTemplate/Editor/GameplayPlans.cs"),
        "presentation_assembler": Path("Assets/GameTemplate/Editor/PresentationSceneAssembler.cs"),
        "asset_binder": Path("Assets/GameTemplate/Editor/GeneratedAssetBinder.cs"),
        "generated_feature_contract": Path(
            "Assets/GameTemplate/Runtime/Core/IGeneratedFeatureModule.cs"
        ),
    }
    SUCCESS_MARKERS: ClassVar[tuple[str, ...]] = (
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
    )

    def __init__(
        self,
        *,
        mode: UnityValidationMode = "auto",
        unity_editor: str | Path | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        if mode not in ("auto", "required", "static"):
            raise ValueError(f"Unsupported Unity validation mode: {mode}")
        if timeout_seconds < 1:
            raise ValueError("Unity validation timeout must be positive")
        self.mode = mode
        self.unity_editor = Path(unity_editor).resolve() if unity_editor else None
        self.timeout_seconds = timeout_seconds

    def validate(
        self,
        project_root: str | Path,
        draft: GameLogicDraft,
        request: ParsedRequest,
        *,
        allow_failed_diagnostic: bool = False,
    ) -> UnityValidationOutcome:
        outcome = UnityValidationOutcome()
        root = Path(project_root).resolve()

        self._check_draft(
            outcome,
            draft,
            allow_failed_diagnostic=allow_failed_diagnostic,
        )
        payloads = self._check_project_structure(outcome, root, draft)
        self._check_contract_consistency(outcome, root, payloads, draft, request)

        if outcome.status == "failed":
            return outcome

        self._run_unity_validation(outcome, root)
        return outcome

    def _check_draft(
        self,
        outcome: UnityValidationOutcome,
        draft: GameLogicDraft,
        *,
        allow_failed_diagnostic: bool = False,
    ) -> None:
        status_valid = draft.get("status") == "generated" or (
            allow_failed_diagnostic
            and draft.get("status") == "failed"
            and bool(draft.get("entry_scene"))
        )
        valid = (
            draft.get("contract_version") == CONTRACT_VERSION
            and status_valid
            and draft.get("engine") == "Unity"
        )
        if valid and draft.get("status") == "failed":
            message = (
                "Failed game draft has a diagnostic Unity project eligible for compilation and "
                "Play Mode evidence collection"
            )
        elif valid:
            message = "Game draft is generated for Unity"
        else:
            message = "Game draft must use the current contract and generated Unity status"
        self._add_check(
            outcome,
            "game.draft",
            valid,
            message,
            error_code="INVALID_GAME_DRAFT",
        )

    def _check_project_structure(
        self,
        outcome: UnityValidationOutcome,
        root: Path,
        draft: GameLogicDraft,
    ) -> dict[str, dict[str, Any]]:
        root_exists = root.is_dir()
        self._add_check(
            outcome,
            "unity.project_root",
            root_exists,
            f"Unity project root: {root}" if root_exists else f"Missing Unity project: {root}",
            error_code="UNITY_PROJECT_MISSING",
        )
        if not root_exists:
            return {}

        files_missing = [
            relative.as_posix()
            for relative in self.REQUIRED_FILE_PATHS.values()
            if not (root / relative).is_file()
        ]
        self._add_check(
            outcome,
            "unity.required_files",
            not files_missing,
            "All required Unity project files exist"
            if not files_missing
            else "Missing files: " + ", ".join(files_missing),
            error_code="UNITY_REQUIRED_FILE_MISSING",
        )

        entry_valid, entry_message = self._validate_entry_scene(root, draft.get("entry_scene"))
        self._add_check(
            outcome,
            "unity.entry_scene",
            entry_valid,
            entry_message,
            error_code="UNITY_ENTRY_SCENE_INVALID",
        )

        payloads: dict[str, dict[str, Any]] = {}
        json_errors: list[str] = []
        for name, relative_path in self.REQUIRED_JSON_PATHS.items():
            path = root / relative_path
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise TypeError("root value is not an object")
                payloads[name] = cast(dict[str, Any], payload)
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
                json_errors.append(f"{relative_path.as_posix()}: {error}")
        self._add_check(
            outcome,
            "unity.json_files",
            not json_errors,
            "All required Unity JSON files are readable"
            if not json_errors
            else "Invalid JSON files: " + "; ".join(json_errors),
            error_code="UNITY_JSON_INVALID",
        )
        return payloads

    def _check_contract_consistency(
        self,
        outcome: UnityValidationOutcome,
        root: Path,
        payloads: dict[str, dict[str, Any]],
        draft: GameLogicDraft,
        request: ParsedRequest,
    ) -> None:
        required_payloads = {
            "design",
            "implementation_plan",
            "implementation_tasks",
            "game_blueprint",
            "game_design",
            "system_design",
            "content_plan",
            "level_plan",
            "balance_plan",
            "presentation_plan",
            "validation_plan",
            "manifest",
            "image_request",
            "sound_request",
        }
        if not required_payloads.issubset(payloads):
            return

        design = payloads["design"]
        manifest = payloads["manifest"]
        image_request = payloads["image_request"]
        sound_request = payloads["sound_request"]
        implementation_plan = payloads["implementation_plan"]
        implementation_tasks = payloads["implementation_tasks"]
        game_blueprint = payloads["game_blueprint"]
        design_documents = {
            key: payloads[key]
            for key in (
                "game_design",
                "system_design",
                "content_plan",
                "level_plan",
                "balance_plan",
                "presentation_plan",
                "validation_plan",
            )
        }
        game_spec = design.get("game_spec")
        if not isinstance(game_spec, dict):
            self._add_check(
                outcome,
                "game.contract_consistency",
                False,
                "GameLogicDesign.game_spec must be an object",
                error_code="GAME_SPEC_INVALID",
            )
            return

        version_values = {
            design.get("contract_version"),
            manifest.get("contract_version"),
            image_request.get("contract_version"),
            sound_request.get("contract_version"),
        }
        version_valid = version_values == {CONTRACT_VERSION}

        genre_values = {
            game_spec.get("genre"),
            manifest.get("genre"),
            image_request.get("genre"),
            sound_request.get("genre"),
        }
        viewpoint_values = {
            game_spec.get("viewpoint"),
            manifest.get("viewpoint"),
            image_request.get("viewpoint"),
            sound_request.get("viewpoint"),
        }
        context_valid = (
            len(genre_values) == 1
            and viewpoint_values == {request["viewpoint"]}
            and image_request.get("image_style") == request["image_style"]
            and sound_request.get("image_style") == request["image_style"]
            and image_request.get("mood_style") == request["mood_style"]
            and sound_request.get("mood_style") == request["mood_style"]
        )

        design_modules = design.get("selected_modules")
        manifest_modules = manifest.get("selected_modules")
        modules_valid = (
            isinstance(design_modules, list)
            and bool(design_modules)
            and design_modules == manifest_modules
            and not design.get("unsupported_mechanics")
        )
        plan_valid, plan_message = self._validate_implementation_plan(
            design,
            implementation_plan,
            manifest,
        )
        tasks_valid, tasks_message = self._validate_implementation_tasks(
            implementation_tasks,
            manifest,
        )
        blueprint_valid = (
            design.get("game_blueprint") == game_blueprint
            and manifest.get("game_blueprint") == "Assets/GameTemplate/Generated/GameBlueprint.json"
            and game_blueprint.get("blueprint_version") == "1.0.0"
            and isinstance(game_blueprint.get("entities"), list)
            and len(game_blueprint["entities"]) >= 2
            and isinstance(game_blueprint.get("content"), list)
            and len(game_blueprint["content"]) >= 3
        )
        v2_valid, v2_message = self._validate_design_v2_documents(
            design,
            design_documents,
            manifest,
        )

        image_ids = self._asset_ids(image_request, "image")
        sound_ids = self._asset_ids(sound_request, "sound")
        assets_valid = (
            image_ids is not None
            and sound_ids is not None
            and image_ids == set(draft["required_image_asset_ids"])
            and sound_ids == set(draft["required_sound_asset_ids"])
        )

        self._add_check(
            outcome,
            "game.contract_version",
            version_valid,
            f"All generated payloads use contract {CONTRACT_VERSION}"
            if version_valid
            else f"Contract versions do not match {CONTRACT_VERSION}",
            error_code="CONTRACT_VERSION_MISMATCH",
        )
        self._add_check(
            outcome,
            "game.context_consistency",
            context_valid,
            "Genre, viewpoint, image style, and mood are consistent"
            if context_valid
            else "Generated project context differs from the parsed request",
            error_code="GAME_CONTEXT_MISMATCH",
        )
        self._add_check(
            outcome,
            "game.module_consistency",
            modules_valid,
            "Selected modules are consistent and fully supported"
            if modules_valid
            else "Selected modules are empty, inconsistent, or unsupported",
            error_code="GAME_MODULE_MISMATCH",
        )
        generated_valid, generated_message = self._validate_generated_modules(
            root,
            design,
            manifest,
        )
        self._add_check(
            outcome,
            "game.generated_modules",
            generated_valid,
            generated_message,
            error_code="GAME_GENERATED_MODULE_INVALID",
        )
        self._add_check(
            outcome,
            "game.implementation_plan",
            plan_valid,
            plan_message,
            error_code="GAME_IMPLEMENTATION_PLAN_INVALID",
        )
        self._add_check(
            outcome,
            "game.implementation_tasks",
            tasks_valid,
            tasks_message,
            error_code="GAME_IMPLEMENTATION_TASKS_INVALID",
        )
        self._add_check(
            outcome,
            "game.blueprint",
            blueprint_valid,
            "Game blueprint is complete and matches the generated design"
            if blueprint_valid
            else "Game blueprint is missing, incomplete, or inconsistent",
            error_code="GAME_BLUEPRINT_INVALID",
        )
        self._add_check(
            outcome,
            "game.design_v2",
            v2_valid,
            v2_message,
            error_code="GAME_DESIGN_V2_INVALID",
        )
        self._add_check(
            outcome,
            "game.asset_ids",
            assets_valid,
            "Required image and sound asset IDs match generation requests"
            if assets_valid
            else "Game draft and asset-request IDs do not match",
            error_code="GAME_ASSET_ID_MISMATCH",
        )

    @staticmethod
    def _validate_design_v2_documents(
        design: dict[str, Any],
        documents: dict[str, dict[str, Any]],
        manifest: dict[str, Any],
    ) -> tuple[bool, str]:
        expected_paths = {
            key: f"Assets/GameTemplate/Generated/Design/{key}.json" for key in documents
        }
        design_v2 = design.get("design_v2")
        level = documents["level_plan"]
        zones = level.get("zones")
        route_valid = True
        if level.get("genre") == "Platformer":
            route_valid = (
                isinstance(zones, list)
                and len(zones) >= 3
                and {zone.get("purpose") for zone in zones if isinstance(zone, dict)}
                == {"tutorial", "challenge", "mastery"}
                and all(
                    isinstance(platform, dict)
                    and platform.get("width", 0) >= level.get("minimum_landing_width", 999)
                    for zone in zones
                    if isinstance(zone, dict)
                    for platform in zone.get("platforms", [])
                )
            )
        contract_valid = True
        try:
            validate_design_v2(cast(DesignV2Bundle, documents))
        except (KeyError, TypeError, ValueError):
            contract_valid = False
        valid = (
            isinstance(design_v2, dict)
            and all(design_v2.get(key) == value for key, value in documents.items())
            and manifest.get("design_documents") == expected_paths
            and documents["game_design"].get("design_version") == "2.0.0"
            and documents["system_design"].get("design_version") == "2.0.0"
            and all(
                documents[key].get("plan_version") == "2.0.0"
                for key in (
                    "content_plan",
                    "level_plan",
                    "balance_plan",
                    "presentation_plan",
                    "validation_plan",
                )
            )
            and route_valid
            and contract_valid
        )
        return (
            valid,
            "Seven design v2 documents are consistent and the level route is structurally safe"
            if valid
            else "Design v2 documents are missing, inconsistent, or contain an unsafe level route",
        )

    @staticmethod
    def _validate_implementation_plan(
        design: dict[str, Any],
        plan: dict[str, Any],
        manifest: dict[str, Any],
    ) -> tuple[bool, str]:
        systems = plan.get("systems")
        content = plan.get("content")
        screens = plan.get("ui_screens")
        scenarios = plan.get("playtest_scenarios")
        valid = (
            design.get("implementation_plan") == plan
            and manifest.get("implementation_plan")
            == "Assets/GameTemplate/Generated/GameImplementationPlan.json"
            and plan.get("plan_version") == "1.0.0"
            and plan.get("complexity_tier") == "advanced_prototype"
            and isinstance(systems, list)
            and len(systems) >= 5
            and isinstance(content, list)
            and len(content) >= 4
            and all(
                isinstance(item, dict) and isinstance(item.get("count"), int) and item["count"] > 0
                for item in content
            )
            and isinstance(screens, list)
            and len(screens) >= 4
            and isinstance(scenarios, list)
            and len(scenarios) >= 3
            and all(
                isinstance(item, dict) and bool(item.get("steps")) and bool(item.get("assertions"))
                for item in scenarios
            )
        )
        if valid:
            return True, "Advanced implementation plan has systems, content, UI, and scenarios"
        return False, "Implementation plan is missing complexity or validation detail"

    @staticmethod
    def _validate_implementation_tasks(
        plan: dict[str, Any],
        manifest: dict[str, Any],
    ) -> tuple[bool, str]:
        tasks = plan.get("tasks")
        if (
            plan.get("plan_version") != "1.0.0"
            or manifest.get("implementation_tasks")
            != "Assets/GameTemplate/Generated/ImplementationTasks.json"
            or not isinstance(plan.get("time_budget_seconds"), int)
            or not isinstance(tasks, list)
            or len(tasks) < 5
        ):
            return False, "Implementation task plan is missing or incomplete"
        task_ids = {task.get("task_id") for task in tasks if isinstance(task, dict)}
        valid_statuses = {"pending", "running", "passed", "failed"}
        valid = len(task_ids) == len(tasks) and all(
            isinstance(task, dict)
            and task.get("status") in valid_statuses
            and isinstance(task.get("attempts"), int)
            and isinstance(task.get("max_attempts"), int)
            and 0 <= task["attempts"] <= task["max_attempts"]
            and isinstance(task.get("dependencies"), list)
            and set(task["dependencies"]).issubset(task_ids)
            and bool(task.get("acceptance_criteria"))
            for task in tasks
        )
        return (
            (True, "Implementation task DAG is bounded and internally consistent")
            if valid
            else (False, "Implementation task DAG contains invalid state or dependencies")
        )

    def _run_unity_validation(self, outcome: UnityValidationOutcome, root: Path) -> None:
        if self.mode == "static":
            self._add_check(
                outcome,
                "unity.batchmode",
                True,
                "Unity Batch Mode intentionally skipped in static mode",
            )
            outcome.issues.append(
                {
                    "code": "UNITY_BATCHMODE_SKIPPED",
                    "severity": "info",
                    "message": "MAINFLOW_UNITY_VALIDATION_MODE=static",
                }
            )
            return

        required_version = self._read_project_version(root)
        editor = self.unity_editor or self.find_unity_editor(required_version)
        if editor is None:
            required = self.mode == "required"
            self._add_check(
                outcome,
                "unity.batchmode",
                not required,
                "Unity Editor was not found; static validation completed"
                if not required
                else "Unity Editor is required but was not found",
                error_code="UNITY_EDITOR_NOT_FOUND" if required else None,
            )
            if not required:
                outcome.issues.append(
                    {
                        "code": "UNITY_EDITOR_NOT_FOUND",
                        "severity": "warning",
                        "message": (
                            "Static validation passed, but C# compilation and scene assembly "
                            "were not executed"
                        ),
                    }
                )
            return

        if not editor.is_file():
            self._add_check(
                outcome,
                "unity.batchmode",
                False,
                f"Configured Unity Editor does not exist: {editor}",
                error_code="UNITY_EDITOR_NOT_FOUND",
            )
            return

        temp_dir = Path(tempfile.mkdtemp(prefix="mainflow-unity-validation-"))
        try:
            log_path = temp_dir / "unity-validation.log"
            command = [
                str(editor),
                "-batchmode",
                "-nographics",
                "-quit",
                "-projectPath",
                str(root),
                "-executeMethod",
                "TeamIdle.GameTemplate.Editor.TemplateProjectBuilder.BuildForBatch",
                "-logFile",
                str(log_path),
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
            log_parts = [completed.stdout or "", completed.stderr or ""]
            if log_path.is_file():
                log_parts.append(log_path.read_text(encoding="utf-8", errors="replace"))
            outcome.unity_log = "\n".join(part for part in log_parts if part)
        except subprocess.TimeoutExpired:
            self._add_check(
                outcome,
                "unity.batchmode",
                False,
                f"Unity validation timed out after {self.timeout_seconds} seconds",
                error_code="UNITY_VALIDATION_TIMEOUT",
            )
            return
        except OSError as error:
            self._add_check(
                outcome,
                "unity.batchmode",
                False,
                f"Failed to start Unity Editor: {error}",
                error_code="UNITY_EDITOR_START_FAILED",
            )
            return
        finally:
            # Unity can keep its log handle briefly after the process exits on Windows.
            # Cleanup failure must not turn a successful compilation into a validation error.
            shutil.rmtree(temp_dir, ignore_errors=True)

        missing_markers = [
            marker for marker in self.SUCCESS_MARKERS if marker not in outcome.unity_log
        ]
        passed = completed.returncode == 0 and not missing_markers
        detail = f"exit={completed.returncode}"
        if missing_markers:
            detail += ", missing=" + ",".join(missing_markers)
        self._add_check(
            outcome,
            "unity.batchmode",
            passed,
            "Unity compilation and scene assembly succeeded" if passed else detail,
            error_code="UNITY_BATCH_VALIDATION_FAILED",
        )
        if passed and os.environ.get("MAINFLOW_UNITY_RUNTIME_TESTS", "1") == "1":
            self._run_runtime_tests(outcome, root, editor)

    def _run_runtime_tests(self, outcome: UnityValidationOutcome, root: Path, editor: Path) -> None:
        """A separate Play Mode process; no -quit until the host-owned test exits."""
        temporary = Path(tempfile.mkdtemp(prefix="mainflow-playtest-"))
        log_path = temporary / "playtest.log"
        try:
            try:
                completed = subprocess.run(
                    [
                        str(editor),
                        "-batchmode",
                        "-nographics",
                        "-projectPath",
                        str(root),
                        "-executeMethod",
                        "TeamIdle.GameTemplate.Editor.RuntimeSmokeValidator.RunForBatch",
                        "-logFile",
                        str(log_path),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                )
                log = (
                    log_path.read_text(encoding="utf-8", errors="replace")
                    if log_path.exists()
                    else ""
                )
                log += (completed.stdout or "") + (completed.stderr or "")
                outcome.unity_log += "\n--- PLAY MODE ---\n" + log
                passed = (
                    completed.returncode == 0
                    and "UNITY_RUNTIME_SMOKE_OK:" in log
                    and "UNITY_VALIDATION_PLAN_OK:" in log
                )
                self._add_check(
                    outcome,
                    "unity.runtime_smoke",
                    passed,
                    "Play Mode smoke tests passed"
                    if passed
                    else "Play Mode smoke tests failed; inspect log",
                    error_code="UNITY_RUNTIME_TEST_FAILED",
                )
            except (subprocess.TimeoutExpired, OSError) as error:
                if log_path.exists():
                    outcome.unity_log += "\n" + log_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                self._add_check(
                    outcome,
                    "unity.runtime_smoke",
                    False,
                    str(error),
                    error_code="UNITY_RUNTIME_EXECUTION_FAILED",
                )
        finally:
            # Unity may release its Windows log handle shortly after the process exits.
            # A best-effort cleanup must never overwrite the actual Play Mode result.
            shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def find_unity_editor(required_version: str | None = None) -> Path | None:
        configured = os.environ.get("UNITY_EDITOR_PATH")
        if configured:
            return Path(configured).expanduser().resolve()

        for executable in ("Unity", "Unity.exe"):
            found = shutil.which(executable)
            if found:
                return Path(found).resolve()

        candidates: list[Path] = []
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            candidates.extend(Path(program_files).glob("Unity/Hub/Editor/*/Editor/Unity.exe"))
        candidates.extend(
            Path("/Applications/Unity/Hub/Editor").glob("*/Unity.app/Contents/MacOS/Unity")
        )
        candidates.extend(Path("/opt/unity/editors").glob("*/Editor/Unity"))
        if required_version:
            exact = [path for path in candidates if path.parent.parent.name == required_version]
            if exact:
                return exact[0]
        return max(candidates, key=lambda path: path.parent.parent.name) if candidates else None

    @staticmethod
    def _read_project_version(root: Path) -> str | None:
        version_path = root / "ProjectSettings/ProjectVersion.txt"
        try:
            for line in version_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("m_EditorVersion:"):
                    return line.partition(":")[2].strip() or None
        except OSError:
            return None
        return None

    @staticmethod
    def _validate_entry_scene(root: Path, entry_scene: object) -> tuple[bool, str]:
        if not isinstance(entry_scene, str) or not entry_scene.strip():
            return False, "Game draft has no entry scene"
        scene = (root.parent.parent / entry_scene).resolve()
        try:
            scene.relative_to(root)
        except ValueError:
            return False, f"Entry scene escapes Unity project: {entry_scene}"
        if not scene.is_file():
            return False, f"Entry scene does not exist: {entry_scene}"
        return True, f"Entry scene exists: {scene.relative_to(root).as_posix()}"

    @staticmethod
    def _asset_ids(payload: dict[str, Any], asset_type: str) -> set[str] | None:
        assets = payload.get("assets")
        if not isinstance(assets, list):
            return None
        ids: list[str] = []
        for item in assets:
            if (
                not isinstance(item, dict)
                or item.get("asset_type") != asset_type
                or not isinstance(item.get("asset_id"), str)
            ):
                return None
            ids.append(cast(str, item["asset_id"]))
        return set(ids) if len(ids) == len(set(ids)) else None

    @staticmethod
    def _validate_generated_modules(
        root: Path,
        design: dict[str, Any],
        manifest: dict[str, Any],
    ) -> tuple[bool, str]:
        generated = design.get("generated_modules", [])
        manifest_generated = manifest.get("generated_modules", [])
        if not isinstance(generated, list) or not isinstance(manifest_generated, list):
            return False, "Generated module metadata must be arrays"
        if not generated:
            return (
                (not manifest_generated),
                "No generated modules were required"
                if not manifest_generated
                else "Manifest contains unexpected generated modules",
            )
        manifest_by_id = {
            item.get("module_id"): item for item in manifest_generated if isinstance(item, dict)
        }
        errors: list[str] = []
        for item in generated:
            if not isinstance(item, dict):
                errors.append("non-object generated module")
                continue
            module_id = item.get("module_id")
            metadata = manifest_by_id.get(module_id)
            if not isinstance(module_id, str) or not isinstance(metadata, dict):
                errors.append(f"missing manifest metadata for {module_id}")
                continue
            relative_path = metadata.get("relative_path")
            expected_hash = item.get("source_sha256")
            if not isinstance(relative_path, str) or not isinstance(expected_hash, str):
                errors.append(f"invalid metadata for {module_id}")
                continue
            source_path = (root / relative_path).resolve()
            try:
                source_path.relative_to(root)
                source = source_path.read_bytes()
            except (ValueError, OSError):
                errors.append(f"missing or unsafe source path for {module_id}")
                continue
            actual_hash = hashlib.sha256(source).hexdigest()
            if actual_hash != expected_hash or metadata.get("source_sha256") != expected_hash:
                errors.append(f"source hash mismatch for {module_id}")
        return (
            not errors,
            "Generated module sources and hashes are valid" if not errors else "; ".join(errors),
        )

    @staticmethod
    def _add_check(
        outcome: UnityValidationOutcome,
        criterion_id: str,
        passed: bool,
        message: str,
        *,
        error_code: str | None = None,
    ) -> None:
        outcome.checks.append(
            {
                "criterion_id": criterion_id,
                "passed": passed,
                "message": message,
            }
        )
        if not passed and error_code:
            outcome.issues.append(
                {
                    "code": error_code,
                    "severity": "error",
                    "message": message,
                }
            )
