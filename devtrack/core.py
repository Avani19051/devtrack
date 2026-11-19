"""Bridge to the C++ core (`dtcore`), with a pure-Python fallback.

The C++ binary is used when it can be found (DEVTRACK_CORE env var, or build/dtcore in the
repo). The fallback keeps the Python layer usable and testable without a compiler, and the
test suite checks that both implementations agree.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def find_core_binary() -> str | None:
    env = os.environ.get("DEVTRACK_CORE")
    if env:
        return env if Path(env).is_file() else None
    candidate = REPO_ROOT / "build" / "dtcore"
    if candidate.is_file():
        return str(candidate)
    return shutil.which("dtcore")


@dataclass
class Issue:
    rule: str
    message: str
    line: int = 0

    def to_dict(self) -> dict:
        return {"rule": self.rule, "message": self.message, "line": self.line}


class CoreError(RuntimeError):
    pass


# ---------------------------------------------------------------- pure-Python fallback

@dataclass
class Rules:
    name_pattern: str = ""
    max_size_kb: int = -1
    required_keys: dict[str, list[str]] = field(default_factory=dict)
    forbidden: list[str] = field(default_factory=list)
    no_trailing_whitespace: bool = False


def parse_rules(text: str) -> Rules:
    r = Rules()
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise CoreError(f"rules line {n}: missing '='")
        key, value = (p.strip() for p in line.split("=", 1))
        if key == "name_pattern":
            r.name_pattern = value
        elif key == "max_size_kb":
            r.max_size_kb = int(value)
        elif key.startswith("required_keys."):
            r.required_keys[key[len("required_keys."):]] = [
                k.strip() for k in value.split(",") if k.strip()
            ]
        elif key == "forbid":
            r.forbidden.append(value)
        elif key == "no_trailing_whitespace":
            r.no_trailing_whitespace = value in ("true", "1")
        else:
            raise CoreError(f"rules line {n}: unknown rule '{key}'")
    return r


def _py_validate(filename: str, content: str, rules: Rules) -> list[Issue]:
    issues: list[Issue] = []
    name = Path(filename).name
    if rules.name_pattern and not re.fullmatch(rules.name_pattern, name):
        issues.append(Issue("name_pattern",
                            f"file name '{name}' does not match {rules.name_pattern}"))
    size = len(content.encode())
    if rules.max_size_kb >= 0 and size > rules.max_size_kb * 1024:
        issues.append(Issue("max_size_kb",
                            f"file is {size // 1024} KB, limit is {rules.max_size_kb} KB"))
    ext = name.rsplit(".", 1)[1] if "." in name else ""
    for key in rules.required_keys.get(ext, []):
        pat = re.compile(rf'("{re.escape(key)}"\s*:)|(^\s*{re.escape(key)}\s*[:=])', re.M)
        if not pat.search(content):
            issues.append(Issue("required_keys", f"missing required key '{key}'"))
    for i, line in enumerate(content.splitlines(), 1):
        for bad in rules.forbidden:
            if bad in line:
                issues.append(Issue("forbid", f"forbidden text '{bad}'", i))
        if rules.no_trailing_whitespace and line and line[-1] in " \t":
            issues.append(Issue("no_trailing_whitespace", "trailing whitespace", i))
    return issues


# ---------------------------------------------------------------- public API

class Core:
    """Hash / diff / validate, preferring the C++ binary."""

    def __init__(self, binary: str | None = "auto"):
        self.binary = find_core_binary() if binary == "auto" else binary

    @property
    def backend(self) -> str:
        return "cpp" if self.binary else "python"

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        proc = subprocess.run([self.binary, *args], capture_output=True, text=True)
        if proc.returncode == 2:
            raise CoreError(proc.stderr.strip() or "dtcore failed")
        return proc

    def hash_file(self, path: str | Path) -> str:
        if self.binary:
            return self._run("hash", str(path)).stdout.strip()
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def diff_files(self, old: str | Path, new: str | Path) -> str:
        """Returns the diff as ' line' / '-line' / '+line' rows."""
        if self.binary:
            return self._run("diff", str(old), str(new)).stdout
        a = Path(old).read_text(errors="replace").splitlines()
        b = Path(new).read_text(errors="replace").splitlines()
        rows = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b,
                                                           autojunk=False).get_opcodes():
            if tag == "equal":
                rows += [" " + x for x in a[i1:i2]]
            else:
                rows += ["-" + x for x in a[i1:i2]]
                rows += ["+" + x for x in b[j1:j2]]
        return "".join(r + "\n" for r in rows)

    def validate_file(self, path: str | Path, rules_path: str | Path) -> list[Issue]:
        if self.binary:
            out = self._run("validate", str(path), str(rules_path)).stdout
            return [Issue(**json.loads(l)) for l in out.splitlines() if l.strip()]
        rules = parse_rules(Path(rules_path).read_text())
        content = Path(path).read_text(errors="replace")
        return _py_validate(str(path), content, rules)


def diff_stats(diff_text: str) -> tuple[int, int]:
    lines = diff_text.splitlines()
    return (sum(l.startswith("+") for l in lines), sum(l.startswith("-") for l in lines))
