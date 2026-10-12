"""Minimal local web entry point for MainFlowChart."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

LOCAL_WEB_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = LOCAL_WEB_ROOT / "static"

app = FastAPI(
    title="MainFlowChart Local Web",
    description="Local-only web shell for the MainFlowChart workflow.",
    version="0.2.0",
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
        "workflow": "not_connected",
        "contract_version": "3.0.0",
    }
