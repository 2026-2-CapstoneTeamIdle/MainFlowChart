"""Local web entry point for configuring and running MainFlowChart."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from service import (
    GenerationRequest,
    LocalWebSettingsStore,
    ModelSettingsUpdate,
    WorkflowJobManager,
)

LOCAL_WEB_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = LOCAL_WEB_ROOT / "static"
settings_store = LocalWebSettingsStore()
job_manager = WorkflowJobManager(settings_store)

app = FastAPI(
    title="MainFlowChart Local Web",
    description="Local-only web shell for the MainFlowChart workflow.",
    version="1.0.1",
)
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Return the local web application shell."""
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    """Report whether the local web server is available."""
    return {
        "service": "main-flow-chart-local-web",
        "status": "ok",
        "workflow": "connected",
        "contract_version": "3.4.0",
    }


@app.get("/api/config/models")
def model_catalog() -> dict[str, object]:
    """Return role choices and only whether each server-side key is configured."""

    return settings_store.public_catalog()


@app.put("/api/config/models")
def update_model_settings(update: ModelSettingsUpdate) -> dict[str, object]:
    """Persist model choices and ignored server-only API-key environment values."""

    try:
        settings_store.save(update)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return settings_store.public_catalog()


@app.post("/api/jobs", status_code=202)
def create_job(request: GenerationRequest) -> dict[str, object]:
    """Start the Condition-to-Feature approval phase for one generation request."""

    try:
        return job_manager.create(request).snapshot()
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str) -> dict[str, object]:
    """Return current status, approved-safe metadata, Feature candidates, and logs."""

    try:
        return job_manager.get(job_id).snapshot()
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/jobs/{job_id}/confirm", status_code=202)
def confirm_job(job_id: str) -> dict[str, object]:
    """Continue the full or asset-free workflow using exactly the shown Features."""

    try:
        return job_manager.confirm(job_id).snapshot()
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/jobs/{job_id}/reject", status_code=202)
def reject_job(job_id: str) -> dict[str, object]:
    """Discard the preview and rerun Condition-to-Feature analysis."""

    try:
        return job_manager.reject(job_id).snapshot()
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str) -> dict[str, object]:
    """Stop feature analysis or game generation and its child process tree."""

    try:
        return job_manager.cancel(job_id).snapshot()
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/jobs/{job_id}/open-unity")
def open_job_unity_project(job_id: str) -> dict[str, str]:
    """Open a completed or failed job's generated project in Unity Editor."""

    try:
        project_root = job_manager.open_unity_editor(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return {"status": "opened", "project_root": str(project_root)}
