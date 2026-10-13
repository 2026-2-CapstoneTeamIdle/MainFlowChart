"""Parse initial input and create the project workspace."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    ParsedRequest,
    ParseInputAgentInput,
    ParseInputAgentOutput,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: user_input
# - 입력 State: image_style, mood_style, genre, condition, custom_image_path(선택)
# - 입력 파일: 없음
# - 출력 State: project_id, parsed_request(ArtifactReference)
# - 출력 파일: data/parsed_request.json
# - 다음 Node: analysis
def parse_input_node(state: ParseInputAgentInput) -> ParseInputAgentOutput:
    """Normalize the request and persist it as the first project artifact."""
    log("유저 입력을 파싱합니다.")

    # TODO: 이후 AdviserAI / LLM을 이용한 실제 요구사항 파싱
    manager = ArtifactManager()
    custom_source: Path | None = None
    custom_suffix = ""
    if state["image_style"] == "Custom":
        custom_source = Path(state["custom_image_path"])
        custom_suffix = custom_source.suffix.lower()
        if custom_suffix not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("Custom image must be a PNG or JPG file")
        content = custom_source.read_bytes()
        is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
        is_jpeg = content.startswith(b"\xff\xd8") and content.endswith(b"\xff\xd9")
        if not (is_png or is_jpeg):
            raise ValueError("Custom image content is not a valid PNG or JPG file")

    project_id = manager.create_project()
    custom_image = None
    if custom_source is not None:
        media_type = mimetypes.guess_type(custom_source.name)[0] or "application/octet-stream"
        custom_image = manager.import_file(
            project_id,
            "image",
            custom_source,
            producer="parse_input",
            filename=f"references/custom_style{custom_suffix}",
            media_type=media_type,
        )

    parsed_request: ParsedRequest = {
        "contract_version": CONTRACT_VERSION,
        "image_style": state["image_style"],
        "mood_style": state["mood_style"],
        "genre": state["genre"],
        "condition": state["condition"].strip(),
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
