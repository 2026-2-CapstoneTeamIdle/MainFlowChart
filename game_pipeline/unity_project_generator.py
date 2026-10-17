"""Generate a ready-to-open Unity project from a normalized game design."""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from game_pipeline.asset_specs import (
    build_image_generation_spec,
    build_sound_generation_spec,
)
from mainflow.contracts import (
    CONTRACT_VERSION,
    ArtifactReference,
    AssetGenerationItem,
    AssetGenerationRequest,
    AssetType,
    GameLogicDesign,
    ImageStyle,
    MoodStyle,
    Viewpoint,
)


@dataclass(frozen=True)
class UnityGenerationResult:
    project_root: Path
    entry_scene: Path
    manifest_path: Path
    build_request_path: Path
    game_blueprint_path: Path
    implementation_tasks_path: Path
    design_document_paths: dict[str, Path]
    image_asset_request_path: Path
    sound_asset_request_path: Path


class UnityProjectGenerator:
    """Copy the Unity template and configure it for one GameLogicDesign."""

    GENERATED_ROOT = Path("Assets/GameTemplate/Generated")
    CONFIG_ASSET = GENERATED_ROOT / "GameTemplateConfig.asset"
    DESIGN_PATH = GENERATED_ROOT / "GameLogicDesign.json"
    BLUEPRINT_PATH = GENERATED_ROOT / "GameBlueprint.json"
    DESIGN_DOCUMENT_ROOT = GENERATED_ROOT / "Design"
    DESIGN_DOCUMENT_NAMES: ClassVar[dict[str, str]] = {
        "game_design": "game_design.json",
        "system_design": "system_design.json",
        "content_plan": "content_plan.json",
        "level_plan": "level_plan.json",
        "balance_plan": "balance_plan.json",
        "presentation_plan": "presentation_plan.json",
        "validation_plan": "validation_plan.json",
    }
    IMPLEMENTATION_PLAN_PATH = GENERATED_ROOT / "GameImplementationPlan.json"
    IMPLEMENTATION_TASKS_PATH = GENERATED_ROOT / "ImplementationTasks.json"
    QUALITY_REPORT_PATH = GENERATED_ROOT / "Validation/GameQualityReport.json"
    BUILD_REQUEST_PATH = GENERATED_ROOT / "GenerationRequest.json"
    ASSET_REQUEST_ROOT = GENERATED_ROOT / "AssetRequests"
    IMAGE_ASSET_REQUEST_PATH = ASSET_REQUEST_ROOT / "image_asset_request.json"
    SOUND_ASSET_REQUEST_PATH = ASSET_REQUEST_ROOT / "sound_asset_request.json"
    GENERATED_SCRIPT_ROOT = GENERATED_ROOT / "Scripts"
    MANIFEST_PATH = Path("GenerationManifest.json")
    ENTRY_SCENE = Path("Assets/Scenes/Bootstrap.unity")
    IGNORED_DIRECTORIES: ClassVar[set[str]] = {
        "Library",
        "Temp",
        "Obj",
        "Logs",
        "UserSettings",
        "MemoryCaptures",
        "Recordings",
        "Builds",
    }

    def __init__(self, template_root: str | Path | None = None) -> None:
        repository_root = Path(__file__).resolve().parent.parent
        self.template_root = Path(template_root or repository_root / "unity_template").resolve()
        self._validate_template()

    def generate(
        self,
        design: GameLogicDesign,
        destination: str | Path,
        *,
        image_style: ImageStyle = "Pixel Art",
        mood_style: MoodStyle = "Fantasy",
        viewpoint: Viewpoint | None = None,
        reference_image: ArtifactReference | None = None,
    ) -> UnityGenerationResult:
        """Generate a project atomically and return its important paths."""

        self._validate_design(design)
        destination_path = Path(destination).resolve()
        if destination_path.exists():
            raise FileExistsError(f"Unity project destination already exists: {destination_path}")

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        staging_path = Path(
            tempfile.mkdtemp(
                prefix=f".{destination_path.name}.",
                suffix=".tmp",
                dir=destination_path.parent,
            )
        )
        try:
            self._copy_template(staging_path)
            self._configure_project(
                staging_path,
                design,
                image_style,
                mood_style,
                viewpoint or design["game_spec"]["viewpoint"],
                reference_image,
            )
            self._commit_staging_directory(staging_path, destination_path)
        except Exception:
            shutil.rmtree(staging_path, ignore_errors=True)
            raise

        return UnityGenerationResult(
            project_root=destination_path,
            entry_scene=destination_path / self.ENTRY_SCENE,
            manifest_path=destination_path / self.MANIFEST_PATH,
            build_request_path=destination_path / self.BUILD_REQUEST_PATH,
            game_blueprint_path=destination_path / self.BLUEPRINT_PATH,
            implementation_tasks_path=destination_path / self.IMPLEMENTATION_TASKS_PATH,
            design_document_paths={
                key: destination_path / self.DESIGN_DOCUMENT_ROOT / filename
                for key, filename in self.DESIGN_DOCUMENT_NAMES.items()
            },
            image_asset_request_path=destination_path / self.IMAGE_ASSET_REQUEST_PATH,
            sound_asset_request_path=destination_path / self.SOUND_ASSET_REQUEST_PATH,
        )

    def update_implementation_tasks(
        self,
        project_root: str | Path,
        task_plan: object,
    ) -> Path:
        root = Path(project_root).resolve()
        path = root / self.IMPLEMENTATION_TASKS_PATH
        if not (root / "ProjectSettings/ProjectVersion.txt").is_file():
            raise ValueError(f"Not a generated Unity project: {root}")
        self._write_json(path, task_plan)
        design_path = root / self.DESIGN_PATH
        design = json.loads(design_path.read_text(encoding="utf-8"))
        if not isinstance(design, dict):
            raise TypeError(f"Generated game design must be a JSON object: {design_path}")
        design["implementation_tasks"] = task_plan
        self._write_json(design_path, design)
        return path

    def update_quality_report(self, project_root: str | Path, report: object) -> Path:
        """Persist post-Play-Mode quality evidence before packaging the project."""

        root = Path(project_root).resolve()
        path = root / self.QUALITY_REPORT_PATH
        if not (root / "ProjectSettings/ProjectVersion.txt").is_file():
            raise ValueError(f"Not a generated Unity project: {root}")
        self._write_json(path, report)
        design_path = root / self.DESIGN_PATH
        design = json.loads(design_path.read_text(encoding="utf-8"))
        if not isinstance(design, dict):
            raise TypeError(f"Generated game design must be a JSON object: {design_path}")
        design["quality_report"] = report
        self._write_json(design_path, design)
        manifest_path = root / self.MANIFEST_PATH
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise TypeError(f"Generation manifest must be a JSON object: {manifest_path}")
        manifest["quality_report"] = self.QUALITY_REPORT_PATH.as_posix()
        self._write_json(manifest_path, manifest)
        return path

    def create_archive(self, project_root: str | Path) -> bytes:
        """Return a deterministic ZIP containing the generated Unity project."""

        root = Path(project_root).resolve()
        if not (root / "ProjectSettings/ProjectVersion.txt").is_file():
            raise ValueError(f"Not a generated Unity project: {root}")

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                relative_path = path.relative_to(root)
                if any(part in self.IGNORED_DIRECTORIES for part in relative_path.parts):
                    continue
                info = zipfile.ZipInfo(
                    f"UnityProject/{relative_path.as_posix()}",
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        return output.getvalue()

    def _validate_template(self) -> None:
        required = [
            self.template_root / "Packages/manifest.json",
            self.template_root / "ProjectSettings/ProjectVersion.txt",
            self.template_root / self.CONFIG_ASSET,
            self.template_root / self.ENTRY_SCENE,
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError("Unity template is incomplete: " + ", ".join(missing))

    @staticmethod
    def _validate_design(design: GameLogicDesign) -> None:
        if design["contract_version"] != CONTRACT_VERSION:
            raise ValueError(f"Unsupported game design contract: {design['contract_version']}")
        if design["game_spec"]["target_engine"] != "Unity":
            raise ValueError("UnityProjectGenerator only supports Unity designs")
        if design["unsupported_mechanics"]:
            raise ValueError(
                "Cannot generate unsupported mechanics: "
                + ", ".join(design["unsupported_mechanics"])
            )
        if len(set(design["selected_modules"])) != len(design["selected_modules"]):
            raise ValueError("selected_modules must not contain duplicate IDs")
        generated_ids = [module["module_id"] for module in design["generated_modules"]]
        if len(generated_ids) != len(set(generated_ids)):
            raise ValueError("generated_modules must not contain duplicate module IDs")
        if not set(generated_ids).issubset(design["selected_modules"]):
            raise ValueError("Every generated module must be selected")

    def _copy_template(self, staging_path: Path) -> None:
        def ignore(_: str, names: list[str]) -> set[str]:
            return {name for name in names if name in self.IGNORED_DIRECTORIES}

        shutil.copytree(
            self.template_root,
            staging_path,
            dirs_exist_ok=True,
            ignore=ignore,
        )

    @staticmethod
    def _commit_staging_directory(
        staging_path: Path,
        destination_path: Path,
        *,
        max_attempts: int = 6,
    ) -> None:
        """Rename an assembled project, tolerating short-lived Windows file locks."""

        for attempt in range(max_attempts):
            try:
                staging_path.replace(destination_path)
                return
            except PermissionError:
                if destination_path.exists() or attempt + 1 >= max_attempts:
                    raise
                time.sleep(0.2 * (attempt + 1))
        raise AssertionError("unreachable")

    def _configure_project(
        self,
        project_root: Path,
        design: GameLogicDesign,
        image_style: ImageStyle,
        mood_style: MoodStyle,
        viewpoint: Viewpoint,
        reference_image: ArtifactReference | None,
    ) -> None:
        game_spec = design["game_spec"]
        config_path = project_root / self.CONFIG_ASSET
        config_text = config_path.read_text(encoding="utf-8")
        replacements = {
            "contractVersion": CONTRACT_VERSION,
            "gameTitle": game_spec["title"],
            "genre": game_spec["genre"],
            "viewpoint": viewpoint,
            "entryScene": self.ENTRY_SCENE.as_posix(),
        }
        for field_name, value in replacements.items():
            config_text, count = re.subn(
                rf"(?m)^  {re.escape(field_name)}:.*$",
                f"  {field_name}: {self._yaml_string(value)}",
                config_text,
            )
            if count != 1:
                raise ValueError(f"Unity config field is missing or duplicated: {field_name}")

        selected_modules = "\n".join(
            f"  - {self._yaml_string(module_id)}" for module_id in design["selected_modules"]
        )
        config_text, count = re.subn(
            r"(?ms)^  selectedModules:\n(?:  - .*\n?)*",
            f"  selectedModules:\n{selected_modules}\n",
            config_text,
        )
        if count != 1:
            raise ValueError("Unity config selectedModules block is missing or duplicated")
        config_path.write_text(config_text, encoding="utf-8", newline="\n")

        generated_root = project_root / self.GENERATED_ROOT
        generated_root.mkdir(parents=True, exist_ok=True)
        self._write_generated_modules(project_root, design)
        self._write_json(generated_root / self.DESIGN_PATH.name, design)
        self._write_json(generated_root / self.BLUEPRINT_PATH.name, design["game_blueprint"])
        for key, filename in self.DESIGN_DOCUMENT_NAMES.items():
            self._write_json(
                project_root / self.DESIGN_DOCUMENT_ROOT / filename,
                design["design_v2"][key],  # type: ignore[literal-required]
            )
        self._write_json(
            project_root / self.IMPLEMENTATION_PLAN_PATH,
            design["implementation_plan"],
        )
        self._write_json(
            project_root / self.IMPLEMENTATION_TASKS_PATH,
            design["implementation_tasks"],
        )

        request = {
            "contract_version": CONTRACT_VERSION,
            "design_id": design["design_id"],
            "entry_scene": self.ENTRY_SCENE.as_posix(),
            "selected_modules": design["selected_modules"],
            "implementation_plan": self.IMPLEMENTATION_PLAN_PATH.as_posix(),
            "implementation_tasks": self.IMPLEMENTATION_TASKS_PATH.as_posix(),
            "game_blueprint": self.BLUEPRINT_PATH.as_posix(),
            "design_documents": {
                key: (self.DESIGN_DOCUMENT_ROOT / filename).as_posix()
                for key, filename in self.DESIGN_DOCUMENT_NAMES.items()
            },
        }
        self._write_json(project_root / self.BUILD_REQUEST_PATH, request)

        image_request = self.build_asset_request(
            design,
            "image",
            image_style=image_style,
            mood_style=mood_style,
            viewpoint=viewpoint,
            reference_image=reference_image,
        )
        sound_request = self.build_asset_request(
            design,
            "sound",
            image_style=image_style,
            mood_style=mood_style,
            viewpoint=viewpoint,
            reference_image=None,
        )
        self._write_json(project_root / self.IMAGE_ASSET_REQUEST_PATH, image_request)
        self._write_json(project_root / self.SOUND_ASSET_REQUEST_PATH, sound_request)

        manifest: dict[str, Any] = {
            "manifest_version": "1.0.0",
            "contract_version": CONTRACT_VERSION,
            "generator": "UnityProjectGenerator",
            "game_title": game_spec["title"],
            "genre": game_spec["genre"],
            "viewpoint": viewpoint,
            "design_id": design["design_id"],
            "entry_scene": self.ENTRY_SCENE.as_posix(),
            "selected_modules": design["selected_modules"],
            "implementation_plan": self.IMPLEMENTATION_PLAN_PATH.as_posix(),
            "implementation_tasks": self.IMPLEMENTATION_TASKS_PATH.as_posix(),
            "game_blueprint": self.BLUEPRINT_PATH.as_posix(),
            "design_documents": {
                key: (self.DESIGN_DOCUMENT_ROOT / filename).as_posix()
                for key, filename in self.DESIGN_DOCUMENT_NAMES.items()
            },
            "generated_modules": [
                {
                    "module_id": module["module_id"],
                    "feature_id": module["feature_id"],
                    "class_name": module["class_name"],
                    "relative_path": (
                        self.GENERATED_SCRIPT_ROOT / f"{module['class_name']}.cs"
                    ).as_posix(),
                    "source_sha256": module["source_sha256"],
                }
                for module in design["generated_modules"]
            ],
            "asset_requirements": game_spec["asset_requirements"],
            "asset_request_files": {
                "image": self.IMAGE_ASSET_REQUEST_PATH.as_posix(),
                "sound": self.SOUND_ASSET_REQUEST_PATH.as_posix(),
            },
            "bootstrap_generation": "on_first_unity_open",
        }
        self._write_json(project_root / self.MANIFEST_PATH, manifest)

    def _write_generated_modules(
        self,
        project_root: Path,
        design: GameLogicDesign,
    ) -> None:
        script_root = project_root / self.GENERATED_SCRIPT_ROOT
        for module in design["generated_modules"]:
            source = module["source_code"].replace("\r\n", "\n").rstrip() + "\n"
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
            if digest != module["source_sha256"]:
                raise ValueError(f"Generated source hash mismatch for {module['module_id']}")
            path = script_root / f"{module['class_name']}.cs"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8", newline="\n")

    @staticmethod
    def build_asset_request(
        design: GameLogicDesign,
        asset_type: AssetType,
        *,
        image_style: ImageStyle,
        mood_style: MoodStyle,
        viewpoint: Viewpoint,
        reference_image: ArtifactReference | None,
    ) -> AssetGenerationRequest:
        """Build an asset request without requiring a generated Unity project.

        Image and sound generation are independent workflow branches.  Keeping
        request construction separate from project generation lets those
        branches continue even when code generation or Unity assembly fails.
        """
        extension = "png" if asset_type == "image" else "wav"
        output_directory = "generated/images" if asset_type == "image" else "generated/sounds"
        assets: list[AssetGenerationItem] = []
        for requirement in design["game_spec"]["asset_requirements"]:
            if requirement["asset_type"] != asset_type:
                continue
            assets.append(
                {
                    **requirement,
                    "suggested_filename": f"{requirement['asset_id']}.{extension}",
                    "unity_binding_key": f"asset_registry:{requirement['asset_id']}",
                    "generation_spec": (
                        build_image_generation_spec(
                            requirement["purpose"], requirement["description"]
                        )
                        if asset_type == "image"
                        else build_sound_generation_spec(
                            requirement["purpose"], requirement["description"]
                        )
                    ),
                }
            )

        return {
            "contract_version": CONTRACT_VERSION,
            "request_id": f"{design['design_id']}-{asset_type}-assets",
            "source_design_id": design["design_id"],
            "game_title": design["game_spec"]["title"],
            "genre": design["game_spec"]["genre"],
            "asset_type": asset_type,
            "image_style": image_style,
            "mood_style": mood_style,
            "viewpoint": viewpoint,
            "reference_image": reference_image,
            "output_directory": output_directory,
            "assets": assets,
        }

    @staticmethod
    def _yaml_string(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
