"""Validate initial input and persist it in the project workspace."""

from __future__ import annotations

from pathlib import Path

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    ParsedRequest,
    ParseInputAgentInput,
    ParseInputAgentOutput,
)
from mainflow.nodes._common import log
from mainflow.nodes.user_input import normalize_user_input


def _validate_custom_image(source_value: str) -> tuple[Path, str, str]:
    """Validate a reference image before a project workspace is created."""
    source = Path(source_value).expanduser()
    if not source.is_file():
        raise ValueError(f"custom_image_path does not point to a file: {source}")

    suffix = source.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("Custom image must use a .png, .jpg, or .jpeg extension")

    try:
        content = source.read_bytes()
    except OSError as error:
        raise ValueError(f"Custom image could not be read: {source}") from error

    is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = content.startswith(b"\xff\xd8") and content.endswith(b"\xff\xd9")
    if suffix == ".png" and not is_png:
        raise ValueError("Custom image extension is .png but its content is not PNG")
    if suffix in {".jpg", ".jpeg"} and not is_jpeg:
        raise ValueError("Custom image extension is JPG but its content is not JPEG")

    media_type = "image/png" if is_png else "image/jpeg"
    return source, suffix, media_type


# Node 계약
# - 이전 Node: user_input
# - 입력 State: image_style, mood_style, genre, viewpoint, condition, custom_image_path(선택)
# - 입력 파일: 없음
# - 출력 State: project_id, parsed_request(ArtifactReference)
# - 출력 파일: data/parsed_request.json, generated/images/references/custom_style.*(선택)
# - 다음 Node: analysis
def parse_input_node(state: ParseInputAgentInput) -> ParseInputAgentOutput:
    """Persist a normalized request without performing semantic analysis."""
    log("사용자 입력을 검증하고 저장합니다.")

    normalized = normalize_user_input(state)
    custom_source: Path | None = None
    custom_suffix = ""
    custom_media_type = ""
    if normalized["image_style"] == "Custom":
        custom_source, custom_suffix, custom_media_type = _validate_custom_image(
            normalized["custom_image_path"]
        )

    manager = ArtifactManager()
    project_id = manager.create_project()
    custom_image = None
    if custom_source is not None:
        custom_image = manager.import_file(
            project_id,
            "image",
            custom_source,
            producer="parse_input",
            filename=f"references/custom_style{custom_suffix}",
            media_type=custom_media_type,
        )

    parsed_request: ParsedRequest = {
        "contract_version": CONTRACT_VERSION,
        "image_style": normalized["image_style"],
        "mood_style": normalized["mood_style"],
        "genre": normalized["genre"],
        "viewpoint": normalized["viewpoint"],
        "condition": normalized["condition"],
        "custom_image": custom_image,
    }
    return {
        "project_id": project_id,
        "parsed_request": manager.write_json(
            project_id,
            "data",
            "parsed_request.json",
            parsed_request,
            producer="parse_input",
        ),
    }
