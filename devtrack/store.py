"""Artifact repository: content-addressed object store + SQLite metadata.

Layout inside a project:
    .devtrack/
        objects/ab/cdef...   file contents, named by SHA-256 (identical content stored once)
        metadata.db          artifacts, versions, validation results
        rules                active validation rules (copied from rules/default.rules)
"""
from __future__ import annotations

import getpass
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .core import Core, Issue, diff_stats

DT_DIR = ".devtrack"
DEFAULT_RULES = Path(__file__).resolve().parent.parent / "rules" / "default.rules"

SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,      -- path relative to project root
    file_type   TEXT NOT NULL,
    owner       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    id          INTEGER PRIMARY KEY,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
    number      INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    author      TEXT NOT NULL,
    message     TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('passed', 'failed')),
    created_at  TEXT NOT NULL,
    UNIQUE (artifact_id, number)
);
CREATE TABLE IF NOT EXISTS issues (
    id          INTEGER PRIMARY KEY,
    version_id  INTEGER NOT NULL REFERENCES versions(id),
    rule        TEXT NOT NULL,
    message     TEXT NOT NULL,
    line        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_sha ON versions(sha256);
"""


class StoreError(RuntimeError):
    pass


@dataclass
class Version:
    path: str
    number: int
    sha256: str
    size_bytes: int
    author: str
    message: str
    status: str
    created_at: str
    issues: list[Issue]

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["issues"] = [i.to_dict() for i in self.issues]
        return d


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def find_root(start: str | Path = ".") -> Path:
    p = Path(start).resolve()
    for d in (p, *p.parents):
        if (d / DT_DIR).is_dir():
            return d
    raise StoreError("not a DevTrack project (run 'devtrack init')")


class Repository:
    def __init__(self, root: str | Path, core: Core | None = None):
        self.root = Path(root).resolve()
        self.dt = self.root / DT_DIR
        if not self.dt.is_dir():
            raise StoreError(f"no {DT_DIR} directory in {self.root}")
        self.core = core or Core()
        self.db = sqlite3.connect(self.dt / "metadata.db", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")

    # ------------------------------------------------------------ setup
    @classmethod
    def init(cls, root: str | Path = ".", rules: str | Path | None = None) -> "Repository":
        root = Path(root).resolve()
        dt = root / DT_DIR
        if dt.exists():
            raise StoreError(f"already initialised: {dt}")
        (dt / "objects").mkdir(parents=True)
        shutil.copyfile(rules or DEFAULT_RULES, dt / "rules")
        repo = cls(root)
        repo.db.executescript(SCHEMA)
        repo.db.commit()
        return repo

    @property
    def rules_path(self) -> Path:
        return self.dt / "rules"

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------ helpers
    def _rel(self, path: str | Path) -> str:
        p = Path(path)
        p = (self.root / p).resolve() if not p.is_absolute() else p.resolve()
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            raise StoreError(f"{path} is outside the project") from None

    def _object_path(self, sha: str) -> Path:
        return self.dt / "objects" / sha[:2] / sha[2:]

    def _artifact_id(self, rel: str) -> int:
        row = self.db.execute("SELECT id FROM artifacts WHERE path = ?", (rel,)).fetchone()
        if not row:
            raise StoreError(f"not tracked: {rel}")
        return row["id"]

    def _version_from_row(self, row: sqlite3.Row, rel: str) -> Version:
        issues = [Issue(r["rule"], r["message"], r["line"]) for r in self.db.execute(
            "SELECT rule, message, line FROM issues WHERE version_id = ? ORDER BY id",
            (row["id"],))]
        return Version(rel, row["number"], row["sha256"], row["size_bytes"], row["author"],
                       row["message"], row["status"], row["created_at"], issues)

    # ------------------------------------------------------------ operations
    def add(self, path: str | Path, message: str, author: str | None = None,
            strict: bool = False) -> Version | None:
        """Stores a new version of `path`. Returns None if content is unchanged.

        With strict=True a file that fails validation is rejected instead of being
        recorded with status 'failed'.
        """
        rel = self._rel(path)
        src = self.root / rel
        if not src.is_file():
            raise StoreError(f"no such file: {rel}")
        author = author or getpass.getuser()

        sha = self.core.hash_file(src)
        issues = self.core.validate_file(src, self.rules_path)
        if strict and issues:
            raise StoreError(f"{rel} failed validation: " +
                             "; ".join(i.message for i in issues))

        row = self.db.execute("SELECT id FROM artifacts WHERE path = ?", (rel,)).fetchone()
        if row:
            art_id = row["id"]
            last = self.db.execute(
                "SELECT sha256, number FROM versions WHERE artifact_id = ? "
                "ORDER BY number DESC LIMIT 1", (art_id,)).fetchone()
            if last and last["sha256"] == sha:
                return None
            number = (last["number"] if last else 0) + 1
        else:
            cur = self.db.execute(
                "INSERT INTO artifacts (path, file_type, owner, created_at) VALUES (?,?,?,?)",
                (rel, src.suffix.lstrip(".") or "none", author, _now()))
            art_id, number = cur.lastrowid, 1

        obj = self._object_path(sha)
        if not obj.exists():
            obj.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, obj)

        status = "failed" if issues else "passed"
        cur = self.db.execute(
            "INSERT INTO versions (artifact_id, number, sha256, size_bytes, author, message, "
            "status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (art_id, number, sha, src.stat().st_size, author, message, status, _now()))
        self.db.executemany(
            "INSERT INTO issues (version_id, rule, message, line) VALUES (?,?,?,?)",
            [(cur.lastrowid, i.rule, i.message, i.line) for i in issues])
        self.db.commit()
        return self.get_version(rel, number)

    def list_artifacts(self) -> list[dict]:
        rows = self.db.execute("""
            SELECT a.path, a.file_type, a.owner, v.number AS latest, v.status, v.created_at
            FROM artifacts a
            JOIN versions v ON v.artifact_id = a.id
            WHERE v.number = (SELECT MAX(number) FROM versions WHERE artifact_id = a.id)
            ORDER BY a.path""")
        return [dict(r) for r in rows]

    def history(self, path: str | Path) -> list[Version]:
        rel = self._rel(path)
        rows = self.db.execute("SELECT * FROM versions WHERE artifact_id = ? ORDER BY number",
                               (self._artifact_id(rel),)).fetchall()
        return [self._version_from_row(r, rel) for r in rows]

    def get_version(self, path: str | Path, number: int | None = None) -> Version:
        rel = self._rel(path)
        art_id = self._artifact_id(rel)
        if number is None:
            row = self.db.execute("SELECT * FROM versions WHERE artifact_id = ? "
                                  "ORDER BY number DESC LIMIT 1", (art_id,)).fetchone()
        else:
            row = self.db.execute("SELECT * FROM versions WHERE artifact_id = ? AND number = ?",
                                  (art_id, number)).fetchone()
        if not row:
            raise StoreError(f"{rel} has no version {number}")
        return self._version_from_row(row, rel)

    def read(self, path: str | Path, number: int | None = None) -> bytes:
        return self._object_path(self.get_version(path, number).sha256).read_bytes()

    def diff(self, path: str | Path, old: int, new: int | None = None) -> dict:
        """Diff between two stored versions (new defaults to latest)."""
        a, b = self.get_version(path, old), self.get_version(path, new)
        text = self.core.diff_files(self._object_path(a.sha256), self._object_path(b.sha256))
        added, removed = diff_stats(text)
        return {"path": a.path, "old": a.number, "new": b.number,
                "added": added, "removed": removed, "diff": text}

    def checkout(self, path: str | Path, number: int, dest: str | Path | None = None) -> Path:
        """Restores a stored version to the working tree (or to `dest`)."""
        v = self.get_version(path, number)
        target = Path(dest) if dest else self.root / v.path
        target.parent.mkdir(parents=True, exist_ok=True)
        # write via temp file so a crash can't leave a half-written artifact
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
            tmp.write(self._object_path(v.sha256).read_bytes())
        Path(tmp.name).replace(target)
        return target

    def verify(self) -> list[str]:
        """Integrity check: every stored object must still hash to its name."""
        problems = []
        for (sha,) in self.db.execute("SELECT DISTINCT sha256 FROM versions"):
            obj = self._object_path(sha)
            if not obj.exists():
                problems.append(f"missing object {sha}")
            elif self.core.hash_file(obj) != sha:
                problems.append(f"corrupted object {sha}")
        return problems
