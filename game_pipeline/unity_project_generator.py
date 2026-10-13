"""Generate a ready-to-open Unity project from a normalized game design."""

from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mainflow.contracts import (
    CONTRACT_VERSION,
    AssetGenerationItem,
    AssetGenerationRequest,
    AssetType,
    GameLogicDesign,
    ImageStyle,
    MoodStyle,
)


@dataclass(frozen=True)
class UnityGenerationResult:
    project_root: Path
    entry_scene: Path
    manifest_path: Path
    build_request_path: Path
    image_asset_request_path: Path
    sound_asset_request_path: Path


class UnityProjectGenerator:
    """Copy the Unity template and configure it for one GameLogicDesign."""

    GENERATED_ROOT = Path("Assets/GameTemplate/Generated")
    CONFIG_ASSET = GENERATED_ROOT / "GameTemplateConfig.asset"
    DESIGN_PATH = GENERATED_ROOT / "GameLogicDesign.json"
    BUILD_REQUEST_PATH = GENERATED_ROOT / "GenerationRequest.json"
    ASSET_REQUEST_ROOT = GENERATED_ROOT / "AssetRequests"
    IMAGE_ASSET_REQUEST_PATH = ASSET_REQUEST_ROOT / "image_asset_request.json"
    SOUND_ASSET_REQUEST_PATH = ASSET_REQUEST_ROOT / "sound_asset_request.json"
    MANIFEST_PATH = Path("GenerationManifest.json")
    ENTRY_SCENE = Path("Assets/Scenes/Bootstrap.unity")
    IGNORED_DIRECTORIES = {
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
            self._configure_project(staging_path, design, image_style, mood_style)
            staging_path.replace(destination_path)
        except Exception:
            shutil.rmtree(staging_path, ignore_errors=True)
            raise

        return UnityGenerationResult(
            project_root=destination_path,
            entry_scene=destination_path / self.ENTRY_SCENE,
            manifest_path=destination_path / self.MANIFEST_PATH,
            build_request_path=destination_path / self.BUILD_REQUEST_PATH,
            image_asset_request_path=destination_path / self.IMAGE_ASSET_REQUEST_PATH,
            sound_asset_request_path=destination_path / self.SOUND_ASSET_REQUEST_PATH,
        )

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

    def _copy_template(self, staging_path: Path) -> None:
        def ignore(_: str, names: list[str]) -> set[str]:
            return {name for name in names if name in self.IGNORED_DIRECTORIES}

        shutil.copytree(
            self.template_root,
            staging_path,
            dirs_exist_ok=True,
            ignore=ignore,
        )

    def _configure_project(
        self,
        project_root: Path,
        design: GameLogicDesign,
        image_style: ImageStyle,
        mood_style: MoodStyle,
    ) -> None:
        game_spec = design["game_spec"]
        config_path = project_root / self.CONFIG_ASSET
        config_text = config_path.read_text(encoding="utf-8")
        replacements = {
            "contractVersion": CONTRACT_VERSION,
            "gameTitle": game_spec["title"],
            "genre": game_spec["genre"],
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
        self._write_json(generated_root / self.DESIGN_PATH.name, design)

        request = {
            "contract_version": CONTRACT_VERSION,
            "design_id": design["design_id"],
            "entry_scene": self.ENTRY_SCENE.as_posix(),
            "selected_modules": design["selected_modules"],
        }
        self._write_json(project_root / self.BUILD_REQUEST_PATH, request)

        image_request = self._build_asset_request(
            design,
            "image",
            creative_style=image_style,
            mood_style=mood_style,
        )
        sound_request = self._build_asset_request(
            design,
            "sound",
            creative_style=mood_style,
            mood_style=mood_style,
        )
        self._write_json(project_root / self.IMAGE_ASSET_REQUEST_PATH, image_request)
        self._write_json(project_root / self.SOUND_ASSET_REQUEST_PATH, sound_request)

        manifest: dict[str, Any] = {
            "manifest_version": "1.0.0",
            "contract_version": CONTRACT_VERSION,
            "generator": "UnityProjectGenerator",
            "game_title": game_spec["title"],
            "genre": game_spec["genre"],
            "design_id": design["design_id"],
            "entry_scene": self.ENTRY_SCENE.as_posix(),
            "selected_modules": design["selected_modules"],
            "asset_requirements": game_spec["asset_requirements"],
            "asset_request_files": {
                "image": self.IMAGE_ASSET_REQUEST_PATH.as_posix(),
                "sound": self.SOUND_ASSET_REQUEST_PATH.as_posix(),
            },
            "bootstrap_generation": "on_first_unity_open",
        }
        self._write_json(project_root / self.MANIFEST_PATH, manifest)

    @staticmethod
    def _build_asset_request(
        design: GameLogicDesign,
        asset_type: AssetType,
        *,
        creative_style: str,
        mood_style: MoodStyle,
    ) -> AssetGenerationRequest:
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
                }
            )

        return {
            "contract_version": CONTRACT_VERSION,
            "request_id": f"{design['design_id']}-{asset_type}-assets",
            "source_design_id": design["design_id"],
            "game_title": design["game_spec"]["title"],
            "genre": design["game_spec"]["genre"],
            "asset_type": asset_type,
            "creative_style": creative_style,
            "mood_style": mood_style,
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
