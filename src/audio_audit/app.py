from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from tkinter import TclError, Tk, filedialog

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from .service import AuditService


BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR = BASE_DIR / "data"


class LoadSessionRequest(BaseModel):
    root_path: str = Field(min_length=1)


class ActionRequest(BaseModel):
    action: str
    tags: list[str] = Field(default_factory=list)
    note: str = ""


class LabelsRequest(BaseModel):
    labels: list[str] = Field(default_factory=list)


def choose_directory() -> str | None:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(mustexist=True)
        return selected or None
    finally:
        root.destroy()


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = AuditService(DATA_DIR / "audit.db")
    app.state.audit_service = service
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Audio Audit", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.post("/api/dialog/select-root")
    def select_root_dialog():
        try:
            path = choose_directory()
        except (RuntimeError, TclError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Unable to open folder picker: {exc}",
            ) from exc
        return {"path": path}

    @app.post("/api/session/load")
    def load_session(request: LoadSessionRequest):
        service: AuditService = app.state.audit_service
        try:
            return service.load_root(request.root_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/roots/{root_id}/labels")
    def update_labels(root_id: int, request: LabelsRequest):
        service: AuditService = app.state.audit_service
        try:
            return service.update_labels(root_id, request.labels)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/files/{file_id}/action")
    def apply_action(file_id: int, request: ActionRequest):
        service: AuditService = app.state.audit_service
        try:
            return service.apply_action(
                file_id,
                action=request.action,
                tags=request.tags,
                note=request.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/roots/{root_id}/undo")
    def undo(root_id: int):
        service: AuditService = app.state.audit_service
        try:
            return service.undo_last(root_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/files/{file_id}/audio")
    def audio(file_id: int):
        service: AuditService = app.state.audit_service
        try:
            audio_path = service.get_audio_path(file_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Missing audio file: {exc}") from exc
        return FileResponse(audio_path)

    @app.get("/api/files/{file_id}/visualization/{kind}")
    def visualization(file_id: int, kind: str, width: int = 900, height: int = 220):
        service: AuditService = app.state.audit_service
        try:
            payload = service.get_visualization(
                file_id,
                kind=kind,
                width=width,
                height=height,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Missing audio file: {exc}") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(content=payload, media_type="image/png")

    @app.get("/api/roots/{root_id}/export")
    def export_root(root_id: int):
        service: AuditService = app.state.audit_service
        try:
            filename, payload = service.export_root(root_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    return app


app = create_app()


def main() -> None:
    uvicorn.run(
        "audio_audit.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
