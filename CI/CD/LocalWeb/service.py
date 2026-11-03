"""Local-only workflow orchestration and secret-safe model configuration."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast, get_args

from pydantic import BaseModel, Field, field_validator, model_validator

from mainflow.contracts import GameGenre, ImageStyle, MoodStyle, Viewpoint

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = Path(os.environ.get("MAINFLOW_WORKSPACE", REPOSITORY_ROOT / "workspace")).resolve()
LOCAL_WEB_STATE_ROOT = WORKSPACE_ROOT / ".localweb"
JOB_ROOT = LOCAL_WEB_STATE_ROOT / "jobs"
SETTINGS_PATH = LOCAL_WEB_STATE_ROOT / "settings.json"
SECRETS_PATH = LOCAL_WEB_STATE_ROOT / "secrets.env"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_LOG_LINES = 10_000
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")

LOCAL_TEXT_MODELS = (
    "gemma4-12b-it-qat-q4-0",
    "qwen2.5-coder-7b-q5-k-m",
    "gemma4-e2b-q4",
    "gemma4-e4b",
)
LOCAL_VISION_MODELS = ("qwen3-vl-4b-instruct-q4-k-m",)
LOCAL_IMAGE_MODELS = ("sd-turbo",)


@dataclass(frozen=True)
class ModelRole:
    """One selectable AI responsibility and its runtime environment names."""

    label: str
    description: str
    provider_environment: str
    model_environment: str
    providers: tuple[str, ...] = ("local", "openai", "gemini")
    local_models: tuple[str, ...] = LOCAL_TEXT_MODELS
    default_provider: str = "local"
    default_model: str = "gemma4-12b-it-qat-q4-0"


MODEL_ROLES: dict[str, ModelRole] = {
    "image_asset_generation": ModelRole(
        "게임 이미지 에셋",
        "실제 게임에 적용할 이미지와 스프라이트를 생성합니다.",
        "MAINFLOW_IMAGE_BACKEND",
        "MAINFLOW_IMAGE_ASSET_MODEL",
        providers=("placeholder", "local", "openai"),
        local_models=LOCAL_IMAGE_MODELS,
        default_provider="placeholder",
        default_model="placeholder",
    ),
    "sound_asset_generation": ModelRole(
        "게임 사운드 에셋",
        "실제 게임에 적용할 효과음과 BGM을 생성합니다.",
        "SOUND_PROVIDER",
        "ELEVENLABS_SFX_MODEL",
        providers=("procedural", "elevenlabs"),
        local_models=("procedural",),
        default_provider="procedural",
        default_model="procedural",
    ),
    "condition_feature_analysis": ModelRole(
        "Condition → Feature",
        "사용자 조건을 원자적인 구현 기능으로 분해합니다.",
        "MAINFLOW_CONDITION_FEATURE_PROVIDER",
        "LLM_CONDITION_FEATURE_ANALYSIS_MODEL",
    ),
    "genre_feature_enrichment": ModelRole(
        "장르·의존 기능 보강",
        "장르 필수 기능과 요청 기능의 선행 기능을 보강합니다.",
        "MAINFLOW_GENRE_FEATURE_PROVIDER",
        "LLM_GENRE_FEATURE_ENRICHMENT_MODEL",
    ),
    "design_v2": ModelRole(
        "게임 설계 문서",
        "게임 설계 문서를 단계별로 생성합니다.",
        "MAINFLOW_DESIGN_V2_PROVIDER",
        "LLM_DESIGN_V2_MODEL",
        providers=("local", "openai", "gemini", "vastai"),
    ),
    "blueprint": ModelRole(
        "Unity Blueprint",
        "씬과 오브젝트 배치 계획을 보강합니다.",
        "MAINFLOW_BLUEPRINT_PROVIDER",
        "LLM_BLUEPRINT_MODEL",
        providers=("local", "openai", "gemini", "vastai"),
    ),
    "feature_code_generation": ModelRole(
        "Feature 코드 생성",
        "기존 모듈에 없는 Unity C# 기능을 생성합니다.",
        "MAINFLOW_FEATURE_PROVIDER",
        "LLM_FEATURE_CODE_GENERATION_MODEL",
        providers=("local", "openai", "gemini", "vastai"),
        default_model="qwen2.5-coder-7b-q5-k-m",
    ),
    "feature_checklist_generation": ModelRole(
        "Feature Checklist",
        "각 Feature의 30개 검증 항목을 생성합니다.",
        "LLM_FEATURE_CHECKLIST_GENERATION_PROVIDER",
        "LLM_FEATURE_CHECKLIST_GENERATION_MODEL",
    ),
    "unity_checklist_test_generation": ModelRole(
        "Unity Test Code",
        "Checklist를 Unity Test Framework 코드로 변환합니다.",
        "LLM_UNITY_CHECKLIST_TEST_GENERATION_PROVIDER",
        "LLM_UNITY_CHECKLIST_TEST_GENERATION_MODEL",
        default_model="qwen2.5-coder-7b-q5-k-m",
    ),
    "project_context_review": ModelRole(
        "프로젝트 통합 검수",
        "조합된 Unity 프로젝트 전체 문맥을 검수합니다.",
        "LLM_PROJECT_CONTEXT_REVIEW_PROVIDER",
        "LLM_PROJECT_CONTEXT_REVIEW_MODEL",
        providers=("local", "openai", "vastai"),
        default_model="qwen2.5-coder-7b-q5-k-m",
    ),
    "feature_checklist_repair": ModelRole(
        "기능 실패 수정",
        "실패한 기능 테스트의 원인을 분석하고 코드를 수정합니다.",
        "LLM_FEATURE_CHECKLIST_REPAIR_PROVIDER",
        "LLM_FEATURE_CHECKLIST_REPAIR_MODEL",
        providers=("local", "openai", "vastai"),
        default_model="qwen2.5-coder-7b-q5-k-m",
    ),
    "game_quality_validator": ModelRole(
        "최종 게임 품질 검수",
        "하드 검증 이후 독립적인 품질 검수를 수행합니다.",
        "LLM_GAME_QUALITY_VALIDATOR_PROVIDER",
        "LLM_GAME_QUALITY_VALIDATOR_MODEL",
        providers=("local", "openai", "vastai"),
        default_model="qwen2.5-coder-7b-q5-k-m",
    ),
    "visual_validation": ModelRole(
        "플레이 화면 비교(VLM)",
        "목표 이미지와 Unity 캡처를 비교합니다.",
        "LLM_VISUAL_VALIDATION_PROVIDER",
        "LLM_VISUAL_VALIDATION_MODEL",
        providers=("local", "openai", "vastai"),
        local_models=LOCAL_VISION_MODELS,
        default_model="qwen3-vl-4b-instruct-q4-k-m",
    ),
    "visual_target_image": ModelRole(
        "검증용 목표 이미지",
        "게임 에셋 백엔드와 별개인 비교 전용 목표 이미지를 생성합니다.",
        "LLM_VISUAL_TARGET_IMAGE_PROVIDER",
        "LLM_VISUAL_TARGET_IMAGE_MODEL",
        providers=("local", "vastai"),
        local_models=LOCAL_IMAGE_MODELS,
        default_model="sd-turbo",
    ),
}

SECRET_ENVIRONMENTS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "vastai": "VASTAI_INFERENCE_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
}


class RoleSelection(BaseModel):
    provider: str
    model: str = Field(min_length=1, max_length=200)

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        normalized = value.strip()
        if not MODEL_PATTERN.fullmatch(normalized):
            raise ValueError("model contains unsupported characters")
        return normalized


class ModelSettingsUpdate(BaseModel):
    roles: dict[str, RoleSelection]
    api_keys: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_roles(self) -> ModelSettingsUpdate:
        if set(self.roles) != set(MODEL_ROLES):
            missing = sorted(set(MODEL_ROLES) - set(self.roles))
            extra = sorted(set(self.roles) - set(MODEL_ROLES))
            raise ValueError(f"roles mismatch; missing={missing}, extra={extra}")
        for role_name, selection in self.roles.items():
            definition = MODEL_ROLES[role_name]
            if selection.provider not in definition.providers:
                raise ValueError(f"{role_name} does not support provider {selection.provider!r}")
            if selection.provider == "local" and selection.model not in definition.local_models:
                raise ValueError(f"{role_name} does not support local model {selection.model!r}")
        for provider, key in self.api_keys.items():
            if provider not in SECRET_ENVIRONMENTS:
                raise ValueError(f"unsupported API key provider: {provider}")
            if "\n" in key or "\r" in key:
                raise ValueError("API keys cannot contain line breaks")
        return self


class UploadedImage(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    media_type: Literal["image/png", "image/jpeg"]
    data_base64: str = Field(min_length=4)


class GenerationRequest(BaseModel):
    mode: Literal["generate", "test-generate"]
    image_style: str
    mood_style: str
    genre: str
    viewpoint: str
    condition: str = Field(min_length=1, max_length=4000)
    custom_image: UploadedImage | None = None

    @model_validator(mode="after")
    def validate_contract_values(self) -> GenerationRequest:
        allowed_values = {
            "image_style": set(get_args(ImageStyle)),
            "mood_style": set(get_args(MoodStyle)),
            "genre": set(get_args(GameGenre)),
            "viewpoint": set(get_args(Viewpoint)),
        }
        for field_name, allowed in allowed_values.items():
            value = cast(str, getattr(self, field_name))
            if value not in allowed:
                raise ValueError(f"unsupported {field_name}: {value}")
        self.condition = self.condition.strip()
        if not self.condition:
            raise ValueError("condition must not be empty")
        if self.image_style == "Custom" and self.custom_image is None:
            raise ValueError("Custom image style requires a PNG/JPG reference")
        return self


@dataclass
class WorkflowJob:
    job_id: str
    mode: str
    request_file: Path
    job_root: Path
    status: str = "analyzing_features"
    stage: str = "condition_feature_analysis"
    logs: list[str] = field(default_factory=list)
    features: list[dict[str, Any]] = field(default_factory=list)
    preview_project_id: str | None = None
    project_id: str | None = None
    error: str | None = None
    process: subprocess.Popen[str] | None = None
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def append_log(self, value: str) -> None:
        line = value.rstrip("\r\n")
        if not line:
            return
        with self.lock:
            self.logs.append(line)
            if len(self.logs) > MAX_LOG_LINES:
                del self.logs[: len(self.logs) - MAX_LOG_LINES]
            with (self.job_root / "workflow.log").open("a", encoding="utf-8") as file:
                file.write(line + "\n")

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "job_id": self.job_id,
                "mode": self.mode,
                "status": self.status,
                "stage": self.stage,
                "features": list(self.features),
                "preview_project_id": self.preview_project_id,
                "project_id": self.project_id,
                "error": self.error,
                "logs": list(self.logs),
            }


class LocalWebSettingsStore:
    """Persist non-secret choices separately from ignored environment secrets."""

    def __init__(self) -> None:
        LOCAL_WEB_STATE_ROOT.mkdir(parents=True, exist_ok=True)

    def load_roles(self) -> dict[str, RoleSelection]:
        defaults = {
            name: RoleSelection(
                provider=definition.default_provider,
                model=definition.default_model,
            )
            for name, definition in MODEL_ROLES.items()
        }
        if not SETTINGS_PATH.is_file():
            return defaults
        try:
            payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            raw_roles = payload.get("roles", {})
            for name, raw in raw_roles.items():
                if name in MODEL_ROLES:
                    selection = RoleSelection.model_validate(raw)
                    definition = MODEL_ROLES[name]
                    if selection.provider in definition.providers:
                        defaults[name] = selection
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return defaults
        return defaults

    def save(self, update: ModelSettingsUpdate) -> None:
        existing_secrets = self.load_secrets()
        supplied_secrets = {
            SECRET_ENVIRONMENTS[provider]: value.strip()
            for provider, value in update.api_keys.items()
            if value.strip()
        }
        available_secrets = {
            **{name: value for name, value in os.environ.items() if value},
            **existing_secrets,
            **supplied_secrets,
        }
        for role_name, selection in update.roles.items():
            required_key = SECRET_ENVIRONMENTS.get(selection.provider)
            if required_key is not None and required_key not in available_secrets:
                raise ValueError(
                    f"{MODEL_ROLES[role_name].label}에 {selection.provider}를 사용하려면 "
                    f"{required_key}를 먼저 등록해야 합니다."
                )
        payload = {"roles": {name: value.model_dump() for name, value in update.roles.items()}}
        _atomic_write_json(SETTINGS_PATH, payload)
        existing_secrets.update(supplied_secrets)
        _write_secrets(existing_secrets)

    def load_secrets(self) -> dict[str, str]:
        if not SECRETS_PATH.is_file():
            return {}
        secrets: dict[str, str] = {}
        for raw_line in SECRETS_PATH.read_text(encoding="utf-8").splitlines():
            if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
                continue
            name, encoded = raw_line.split("=", 1)
            if name not in SECRET_ENVIRONMENTS.values():
                continue
            try:
                value = json.loads(encoded)
            except json.JSONDecodeError:
                continue
            if isinstance(value, str) and value:
                secrets[name] = value
        return secrets

    def public_catalog(self) -> dict[str, Any]:
        selections = self.load_roles()
        secrets = self.load_secrets()
        return {
            "roles": [
                {
                    "id": name,
                    "label": definition.label,
                    "description": definition.description,
                    "providers": list(definition.providers),
                    "local_models": list(definition.local_models),
                    "selection": selections[name].model_dump(),
                }
                for name, definition in MODEL_ROLES.items()
            ],
            "api_keys": {
                provider: {
                    "configured": environment_name in secrets
                    or bool(os.environ.get(environment_name, "").strip())
                }
                for provider, environment_name in SECRET_ENVIRONMENTS.items()
            },
        }

    def process_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(self.load_secrets())
        for name, selection in self.load_roles().items():
            definition = MODEL_ROLES[name]
            environment[definition.provider_environment] = selection.provider
            environment[definition.model_environment] = selection.model
            if name == "image_asset_generation":
                image_model_environment = (
                    "MAINFLOW_LOCAL_IMAGE_MODEL"
                    if selection.provider == "local"
                    else "MAINFLOW_OPENAI_IMAGE_MODEL"
                )
                environment[image_model_environment] = selection.model
            elif name == "sound_asset_generation":
                environment["ELEVENLABS_SFX_MODEL"] = (
                    "" if selection.model in {"auto", "procedural"} else selection.model
                )
        target = self.load_roles()["visual_target_image"]
        environment["MAINFLOW_VISUAL_TARGET_AI"] = (
            "sd_turbo" if target.provider == "local" and target.model == "sd-turbo" else ""
        )
        environment["LLM_VISUAL_TARGET_IMAGE_PROVIDER"] = target.provider
        environment["LLM_VISUAL_TARGET_IMAGE_MODEL"] = target.model
        environment["MAINFLOW_WORKSPACE"] = str(WORKSPACE_ROOT)
        environment["PYTHONUNBUFFERED"] = "1"
        return environment


class WorkflowJobManager:
    """Run feature approval and generation as observable child processes."""

    def __init__(self, settings: LocalWebSettingsStore) -> None:
        self.settings = settings
        self.jobs: dict[str, WorkflowJob] = {}
        self.lock = threading.RLock()
        JOB_ROOT.mkdir(parents=True, exist_ok=True)

    def create(self, request: GenerationRequest) -> WorkflowJob:
        job_id = uuid.uuid4().hex
        job_root = JOB_ROOT / job_id
        job_root.mkdir(parents=True, exist_ok=False)
        request_payload: dict[str, Any] = {
            "image_style": request.image_style,
            "mood_style": request.mood_style,
            "genre": request.genre,
            "viewpoint": request.viewpoint,
            "condition": request.condition,
        }
        if request.custom_image is not None:
            custom_path = _save_custom_image(job_root, request.custom_image)
            request_payload["custom_image_path"] = str(custom_path)
        request_file = job_root / "request.json"
        _atomic_write_json(request_file, request_payload)
        job = WorkflowJob(job_id, request.mode, request_file, job_root)
        with self.lock:
            self.jobs[job_id] = job
        job.append_log(f"[WEB] 작업 {job_id}의 Feature 분석을 시작합니다.")
        self._start_preview(job)
        return job

    def get(self, job_id: str) -> WorkflowJob:
        with self.lock:
            try:
                return self.jobs[job_id]
            except KeyError as error:
                raise KeyError(f"unknown workflow job: {job_id}") from error

    def confirm(self, job_id: str) -> WorkflowJob:
        job = self.get(job_id)
        with job.lock:
            if job.status != "awaiting_confirmation":
                raise ValueError("Feature 확인 대기 상태에서만 Confirm할 수 있습니다.")
            job.status = "running"
            job.stage = "workflow"
        job.append_log("[WEB] Feature 구성을 승인했습니다. 게임 생성 단계를 계속합니다.")
        thread = threading.Thread(target=self._run_generation, args=(job,), daemon=True)
        thread.start()
        return job

    def reject(self, job_id: str) -> WorkflowJob:
        job = self.get(job_id)
        with job.lock:
            if job.status != "awaiting_confirmation":
                raise ValueError("Feature 확인 대기 상태에서만 Reject할 수 있습니다.")
            job.status = "analyzing_features"
            job.stage = "condition_feature_analysis"
            job.features = []
            job.error = None
        job.append_log("[WEB] Feature 구성을 거절했습니다. Condition 분석을 다시 실행합니다.")
        self._start_preview(job)
        return job

    def _start_preview(self, job: WorkflowJob) -> None:
        thread = threading.Thread(target=self._run_preview, args=(job,), daemon=True)
        thread.start()

    def _run_preview(self, job: WorkflowJob) -> None:
        preview_path = job.job_root / "feature_preview.json"
        preview_path.unlink(missing_ok=True)
        command = [
            sys.executable,
            "-m",
            "mainflow.preview_features",
            "--request-file",
            str(job.request_file),
            "--workspace",
            str(WORKSPACE_ROOT),
            "--output-file",
            str(preview_path),
        ]
        return_code = self._stream_process(job, command)
        if return_code != 0 or not preview_path.is_file():
            self._fail(job, "Condition → Feature 분석 프로세스가 실패했습니다.")
            return
        try:
            payload = json.loads(preview_path.read_text(encoding="utf-8"))
            features = payload["features"]
            if not isinstance(features, list) or not features:
                raise ValueError("feature preview is empty")
            with job.lock:
                job.features = features
                job.preview_project_id = str(payload["project_id"])
                job.status = "awaiting_confirmation"
                job.stage = "feature_confirmation"
            job.append_log(
                f"[WEB] {len(features)}개 Feature 분석이 끝났습니다. Confirm 또는 Reject를 선택하세요."
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            self._fail(job, f"Feature 분석 결과를 읽지 못했습니다: {error}")

    def _run_generation(self, job: WorkflowJob) -> None:
        preview_path = job.job_root / "feature_preview.json"
        try:
            preview = json.loads(preview_path.read_text(encoding="utf-8"))
            approved_logic_path = Path(preview["logic_analysis_path"]).resolve()
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            self._fail(job, f"승인된 Feature 파일을 읽지 못했습니다: {error}")
            return
        environment = self.settings.process_environment()
        environment["MAINFLOW_APPROVED_LOGIC_ANALYSIS"] = str(approved_logic_path)
        command = [
            sys.executable,
            "-m",
            "mainflow.run_flow",
            "--request-file",
            str(job.request_file),
            "--workspace",
            str(WORKSPACE_ROOT),
        ]
        if job.mode == "test-generate":
            command.append("--game-test")
        else:
            command.append("--visual-validation")
        return_code = self._stream_process(job, command, environment)
        if return_code != 0:
            self._fail(job, f"게임 생성 프로세스가 종료 코드 {return_code}로 실패했습니다.")
            return
        with job.lock:
            job.status = "completed"
            job.stage = "completed"
            job.project_id = _latest_project_id_from_logs(job.logs)
        job.append_log("[WEB] 게임 생성 파이프라인이 완료되었습니다.")

    def _stream_process(
        self,
        job: WorkflowJob,
        command: list[str],
        environment: dict[str, str] | None = None,
    ) -> int:
        runtime_environment = environment or self.settings.process_environment()
        process = subprocess.Popen(
            command,
            cwd=REPOSITORY_ROOT,
            env=runtime_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        with job.lock:
            job.process = process
        assert process.stdout is not None
        for line in process.stdout:
            job.append_log(line)
        return_code = process.wait()
        with job.lock:
            job.process = None
        return return_code

    @staticmethod
    def _fail(job: WorkflowJob, message: str) -> None:
        with job.lock:
            job.status = "failed"
            job.stage = "failed"
            job.error = message
        job.append_log(f"[WEB][ERROR] {message}")


def _save_custom_image(job_root: Path, upload: UploadedImage) -> Path:
    try:
        content = base64.b64decode(upload.data_base64, validate=True)
    except ValueError as error:
        raise ValueError("custom image is not valid base64") from error
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("custom image must be between 1 byte and 10 MiB")
    is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = content.startswith(b"\xff\xd8") and content.endswith(b"\xff\xd9")
    if upload.media_type == "image/png" and not is_png:
        raise ValueError("custom image content is not PNG")
    if upload.media_type == "image/jpeg" and not is_jpeg:
        raise ValueError("custom image content is not JPEG")
    suffix = ".png" if is_png else ".jpg"
    stem = SAFE_FILENAME_PATTERN.sub("_", Path(upload.name).stem).strip("._") or "custom_style"
    destination = job_root / f"{stem}{suffix}"
    destination.write_bytes(content)
    return destination


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_secrets(secrets: dict[str, str]) -> None:
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = SECRETS_PATH.with_suffix(".tmp")
    lines = [
        "# LocalWeb server-only secrets. Never sent to workflow State or model prompts.",
        *(f"{name}={json.dumps(value)}" for name, value in sorted(secrets.items())),
        "",
    ]
    temporary.write_text("\n".join(lines), encoding="utf-8")
    os.replace(temporary, SECRETS_PATH)
    try:
        SECRETS_PATH.chmod(0o600)
    except OSError:
        pass


def _latest_project_id_from_logs(logs: list[str]) -> str | None:
    pattern = re.compile(r'"project_id"\s*:\s*"(\d{8}_\d{2,})"')
    for line in reversed(logs):
        match = pattern.search(line)
        if match:
            return match.group(1)
    return None
