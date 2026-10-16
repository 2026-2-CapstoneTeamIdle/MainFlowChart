"""Local web entry point for MainFlowChart.

Accepts the contract 3.1.0 request from the browser, runs the LangGraph
workflow in the background and exposes progress, results and artifacts.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, cast, get_args

LOCAL_WEB_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = LOCAL_WEB_ROOT.parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from workflow_runner import WorkflowRunner, serialize

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    GameGenre,
    ImageStyle,
    MoodStyle,
    Viewpoint,
)
from mainflow.run_flow import load_request

STATIC_ROOT = LOCAL_WEB_ROOT / "static"
UPLOAD_DIRECTORY = "_uploads"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_CONDITION_LENGTH = 300
IMAGE_SIGNATURES = {".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",)}

app = FastAPI(
    title="MainFlowChart Local Web",
    description="Local-only web shell for the MainFlowChart workflow.",
    version="0.3.0",
)
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
runner = WorkflowRunner()


def _options() -> dict[str, list[str]]:
    return {
        "image_style": list(get_args(ImageStyle)),
        "mood_style": list(get_args(MoodStyle)),
        "genre": list(get_args(GameGenre)),
        "viewpoint": list(get_args(Viewpoint)),
    }


def _workflow_status() -> tuple[str, list[str], str | None]:
    try:
        return "connected", runner.node_names(), None
    except Exception as error:  # noqa: BLE001 - reported through /api/health
        return "unavailable", [], f"{type(error).__name__}: {error}"


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Return the local web application shell."""
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Report whether the server and the LangGraph workflow are available."""
    workflow, _, error = _workflow_status()
    return {
        "service": "main-flow-chart-local-web",
        "status": "ok",
        "workflow": workflow,
        "workflow_error": error,
        "busy": runner.busy(),
        "contract_version": CONTRACT_VERSION,
    }


@app.get("/api/workflow")
def workflow() -> dict[str, Any]:
    """Input options from the contract and the graph's node order."""
    status, nodes, error = _workflow_status()
    return {"status": status, "error": error, "nodes": nodes, "options": _options()}


def _save_custom_image(run_key: str, upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    suffix = ".jpg" if suffix == ".jpeg" else suffix
    if suffix not in IMAGE_SIGNATURES:
        raise HTTPException(422, "Custom 이미지는 PNG 또는 JPG 파일이어야 합니다.")
    content = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Custom 이미지는 10MB 이하여야 합니다.")
    if not content.startswith(IMAGE_SIGNATURES[suffix]):
        raise HTTPException(422, "파일 내용이 PNG/JPG 형식이 아닙니다.")
    directory = ArtifactManager().workspace_root / UPLOAD_DIRECTORY / run_key
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"custom_reference{suffix}"
    target.write_bytes(content)
    return target


@app.post("/api/runs", status_code=202)
def create_run(
    image_style: Annotated[str, Form()],
    mood_style: Annotated[str, Form()],
    genre: Annotated[str, Form()],
    viewpoint: Annotated[str, Form()],
    condition: Annotated[str, Form()],
    custom_image: Annotated[UploadFile | None, File()] = None,
) -> dict[str, Any]:
    """Validate the request like the CLI does and start a workflow run."""
    condition = condition.strip()
    if len(condition) > MAX_CONDITION_LENGTH:
        raise HTTPException(422, f"조건은 {MAX_CONDITION_LENGTH}자 이하로 입력하세요.")

    custom_path = None
    has_upload = custom_image is not None and bool(custom_image.filename)
    if image_style == "Custom" and has_upload:
        custom_path = _save_custom_image(f"upload-{uuid.uuid4().hex[:12]}", custom_image)  # type: ignore[arg-type]
    arguments = SimpleNamespace(
        request_file=None,
        image_style=image_style,
        mood_style=mood_style,
        genre=genre,
        viewpoint=viewpoint,
        condition=condition,
        custom_image=custom_path,
    )
    try:
        initial_state = cast(dict[str, Any], load_request(arguments))  # type: ignore[arg-type]
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    public_request = {
        key: initial_state[key]
        for key in ("image_style", "mood_style", "genre", "viewpoint", "condition")
    }
    public_request["custom_image"] = custom_image.filename if custom_path and custom_image else None
    return serialize(runner.submit(initial_state, public_request))


@app.get("/api/runs")
def list_runs() -> list[dict[str, Any]]:
    return [serialize(run) for run in runner.list()]


def _run_or_404(run_id: str):
    run = runner.get(run_id)
    if run is None:
        raise HTTPException(404, "Unknown run_id")
    return run


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return serialize(_run_or_404(run_id))


@app.get("/api/runs/{run_id}/artifacts")
def list_run_artifacts(run_id: str) -> list[dict[str, Any]]:
    run = _run_or_404(run_id)
    if not run.project_id:
        return []
    return [
        {
            key: reference[key]
            for key in (
                "artifact_id",
                "category",
                "relative_path",
                "media_type",
                "size_bytes",
                "producer",
            )
        }
        for reference in ArtifactManager().list_artifacts(run.project_id)
    ]


@app.get("/api/runs/{run_id}/artifacts/{artifact_id}")
def download_artifact(run_id: str, artifact_id: str, inline: bool = False) -> Response:
    """Return an artifact after ArtifactManager verifies its size and SHA-256.

    ``inline=true`` lets the browser play audio in place instead of downloading.
    """
    run = _run_or_404(run_id)
    if not run.project_id:
        raise HTTPException(404, "Run has no project yet")
    manager = ArtifactManager()
    try:
        reference = manager.get_artifact(run.project_id, artifact_id)
    except (KeyError, ValueError) as error:
        raise HTTPException(404, "Unknown artifact_id") from error
    content = manager.read_bytes(reference)
    filename = Path(reference["relative_path"]).name
    return Response(
        content,
        media_type=reference["media_type"],
        headers={
            "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{filename}"'
        },
    )
