"""FastAPI REST API over a DevTrack repository.

Run:  devtrack serve      (then open http://127.0.0.1:8000/docs for interactive docs)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from . import __version__
from .core import Core
from .store import Repository, StoreError
from .triage import triage


class TriageRequest(BaseModel):
    log: str


def create_app(root: str | Path) -> FastAPI:
    repo = Repository(root)
    app = FastAPI(title="DevTrack API", version=__version__,
                  description="Version management for engineering artifacts")

    def _guard(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except StoreError as e:
            msg = str(e)
            raise HTTPException(404 if "not tracked" in msg or "no version" in msg else 400,
                                msg) from None

    @app.get("/health")
    def health():
        return {"status": "ok", "core_backend": repo.core.backend}

    @app.get("/artifacts")
    def list_artifacts():
        return repo.list_artifacts()

    @app.post("/artifacts", status_code=201)
    async def upload(path: str = Form(...), message: str = Form(...),
                     author: str = Form("api"), strict: bool = Form(False),
                     file: UploadFile = File(...)):
        """Upload a file as a new version of `path` (relative to the project root)."""
        target = (repo.root / path).resolve()
        if repo.root not in target.parents:
            raise HTTPException(400, "path must be inside the project")
        if repo.dt in target.parents or target == repo.dt:
            raise HTTPException(400, "cannot write into .devtrack")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(await file.read())
        v = _guard(repo.add, path, message, author, strict)
        if v is None:
            return {"path": path, "unchanged": True}
        return v.to_dict()

    @app.get("/artifacts/{path:path}/versions")
    def history(path: str):
        return [v.to_dict() for v in _guard(repo.history, path)]

    @app.get("/artifacts/{path:path}/versions/{number}")
    def version(path: str, number: int):
        return _guard(repo.get_version, path, number).to_dict()

    @app.get("/artifacts/{path:path}/versions/{number}/content")
    def content(path: str, number: int):
        return Response(_guard(repo.read, path, number),
                        media_type="application/octet-stream")

    @app.get("/artifacts/{path:path}/diff")
    def diff(path: str, old: int, new: int | None = None):
        return _guard(repo.diff, path, old, new)

    @app.post("/validate")
    async def validate(file: UploadFile = File(...)):
        """Dry-run validation against the project's rules (nothing is stored)."""
        suffix = Path(file.filename or "upload").name
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / suffix
            p.write_bytes(await file.read())
            issues = Core(repo.core.binary).validate_file(p, repo.rules_path)
        return {"file": suffix, "passed": not issues, "issues": [i.to_dict() for i in issues]}

    @app.post("/triage")
    def triage_log(req: TriageRequest):
        return triage(req.log)

    @app.get("/verify")
    def verify():
        problems = repo.verify()
        return {"ok": not problems, "problems": problems}

    return app
