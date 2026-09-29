"""HTTP and WebSocket routes for the dashboard."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .files import FileConflict, read_backup, read_backups, read_file, read_directory, write_file
from .macros import MacroStore
from .metrics import MetricsSampler
from .terminal import serve_terminal


STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {"app.css", "app.js", "console.css", "console.js", "manage.css", "theme.js", "favicon.svg"}


class FileUpdate(BaseModel):
    path: str
    content: str
    revision: str | None = None


class MacroUpdate(BaseModel):
    label: str = ""
    command: str = ""
    file: str = ""
    open_url: str = ""


def create_app(sampler: MetricsSampler, state_dir: Path | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    state_dir = state_dir or Path(os.environ.get("DASHBOARD_STATE_DIR", "/var/lib/server-dashboard" if os.name == "posix" else str(Path.home() / ".server-dashboard")))
    macros = MacroStore(state_dir)

    @app.get("/api/health")
    def health() -> JSONResponse:
        snapshot, _ = sampler.read()
        return JSONResponse({"status": "ok" if snapshot else "starting"}, status_code=200 if snapshot else 503, headers={"Cache-Control": "no-store"})

    @app.get("/api/metrics")
    def metrics() -> JSONResponse:
        snapshot, history = sampler.read()
        if snapshot is None:
            return JSONResponse({"error": "Metrics are starting"}, status_code=503, headers={"Cache-Control": "no-store"})
        return JSONResponse({"current": snapshot, "history": history}, headers={"Cache-Control": "no-store"})

    @app.get("/api/console/status")
    def console_status() -> dict[str, Any]:
        return {"terminal_available": os.name == "posix", "privileged": os.name == "posix" and os.geteuid() == 0, "home": str(Path.home())}

    @app.get("/api/files")
    def files(path: str = "/") -> dict[str, Any]:
        try:
            return read_directory(path)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/file")
    def file(path: str) -> dict[str, Any]:
        try:
            return read_file(path)
        except (OSError, ValueError, UnicodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/file")
    def save_file(update: FileUpdate) -> dict[str, Any]:
        try:
            return write_file(update.path, update.content, update.revision, state_dir)
        except FileConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, ValueError, UnicodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/backups")
    def backups(path: str) -> dict[str, Any]:
        try:
            return {"backups": read_backups(path, state_dir)}
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/backup")
    def backup(path: str, id: str) -> dict[str, Any]:
        try:
            return read_backup(path, id, state_dir)
        except (OSError, ValueError, UnicodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/macros")
    def list_macros() -> dict[str, Any]:
        try:
            return {"macros": macros.list()}
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.put("/api/macros/{name}")
    def save_macro(name: str, update: MacroUpdate) -> dict[str, Any]:
        try:
            return macros.save(name, update.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.delete("/api/macros/{name}")
    def delete_macro(name: str) -> dict[str, bool]:
        try:
            macros.delete(name)
            return {"deleted": True}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Макрос не найден") from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/macros/{name}/run")
    async def run_macro(name: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(macros.run, name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Макрос не найден") from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.websocket("/ws/terminal")
    async def terminal(websocket: WebSocket) -> None:
        await serve_terminal(websocket)

    @app.get("/")
    @app.get("/index.html")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/terminal")
    def terminal_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "terminal.html", headers={"Cache-Control": "no-store"})

    @app.get("/{filename}")
    def static_file(filename: str) -> FileResponse:
        if filename not in STATIC_FILES:
            raise HTTPException(status_code=404)
        return FileResponse(STATIC_DIR / filename, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return app


def serve(sampler: MetricsSampler, host: str = "127.0.0.1", port: int = 5100) -> None:
    uvicorn.run(create_app(sampler), host=host, port=port, ws="websockets-sansio", access_log=False)
