"""devtrack command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import Core
from .store import Repository, StoreError, find_root
from .triage import format_report, triage


def _repo() -> Repository:
    return Repository(find_root())


def cmd_init(a):
    repo = Repository.init(".", a.rules)
    print(f"Initialised DevTrack project in {repo.dt} (core backend: {repo.core.backend})")


def cmd_add(a):
    repo = _repo()
    code = 0
    for path in a.paths:
        try:
            v = repo.add(path, a.message, a.author, strict=a.strict)
        except StoreError as e:
            print(f"rejected  {path}: {e}", file=sys.stderr)
            code = 1
            continue
        if v is None:
            print(f"unchanged {path}")
            continue
        flag = "ok " if v.status == "passed" else "WARN"
        print(f"{flag} {v.path} -> v{v.number} ({v.sha256[:10]})")
        for i in v.issues:
            loc = f":{i.line}" if i.line else ""
            print(f"     {i.rule}{loc}: {i.message}")
        if v.status == "failed":
            code = 1
    return code


def cmd_ls(a):
    rows = _repo().list_artifacts()
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("no artifacts tracked")
        return
    print(f"{'PATH':40} {'TYPE':6} {'VER':>4}  {'STATUS':7} UPDATED")
    for r in rows:
        print(f"{r['path']:40} {r['file_type']:6} {r['latest']:>4}  {r['status']:7} "
              f"{r['created_at']}")


def cmd_log(a):
    for v in _repo().history(a.path):
        print(f"v{v.number}  {v.sha256[:10]}  {v.status:6}  {v.author:10}  "
              f"{v.created_at}  {v.message}")


def cmd_show(a):
    sys.stdout.buffer.write(_repo().read(a.path, a.version))


def cmd_diff(a):
    d = _repo().diff(a.path, a.old, a.new)
    print(f"--- {d['path']} v{d['old']}\n+++ {d['path']} v{d['new']}  "
          f"(+{d['added']} -{d['removed']})")
    sys.stdout.write(d["diff"] if a.full else
                     "".join(l + "\n" for l in d["diff"].splitlines() if l[:1] in "+-"))


def cmd_checkout(a):
    out = _repo().checkout(a.path, a.version, a.output)
    print(f"restored {a.path} v{a.version} -> {out}")


def cmd_validate(a):
    try:
        rules = a.rules or str(find_root() / ".devtrack" / "rules")
    except StoreError:
        rules = str(Path(__file__).resolve().parent.parent / "rules" / "default.rules")
    core, code = Core(), 0
    for path in a.paths:
        issues = core.validate_file(path, rules)
        print(f"{'PASS' if not issues else 'FAIL'} {path}")
        for i in issues:
            print(f"     {i.rule}{':' + str(i.line) if i.line else ''}: {i.message}")
        code |= bool(issues)
    return code


def cmd_verify(a):
    problems = _repo().verify()
    for p in problems:
        print(p)
    print("store OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_triage(a):
    log = sys.stdin.read() if a.log == "-" else Path(a.log).read_text(errors="replace")
    report = triage(log)
    print(json.dumps(report, indent=2) if a.json else format_report(report))


def cmd_serve(a):
    import uvicorn
    from .api import create_app
    uvicorn.run(create_app(find_root()), host=a.host, port=a.port)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="devtrack",
                                description="Version management for engineering artifacts")
    p.add_argument("--version", action="version", version=f"devtrack {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create a .devtrack store in the current directory")
    s.add_argument("--rules", help="validation rules file (default: rules/default.rules)")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("add", help="validate and store a new version of files")
    s.add_argument("paths", nargs="+")
    s.add_argument("-m", "--message", required=True)
    s.add_argument("--author")
    s.add_argument("--strict", action="store_true", help="reject files that fail validation")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("ls", help="list tracked artifacts")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_ls)

    s = sub.add_parser("log", help="version history of an artifact")
    s.add_argument("path")
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("show", help="print a stored version")
    s.add_argument("path")
    s.add_argument("-v", "--version", type=int)
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("diff", help="diff two versions (new defaults to latest)")
    s.add_argument("path")
    s.add_argument("old", type=int)
    s.add_argument("new", type=int, nargs="?")
    s.add_argument("--full", action="store_true", help="include unchanged lines")
    s.set_defaults(fn=cmd_diff)

    s = sub.add_parser("checkout", help="restore a stored version")
    s.add_argument("path")
    s.add_argument("version", type=int)
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_checkout)

    s = sub.add_parser("validate", help="check files against rules without storing them")
    s.add_argument("paths", nargs="+")
    s.add_argument("--rules")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("verify", help="check stored objects for corruption")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("triage", help="analyse a failing test log ('-' = stdin)")
    s.add_argument("log")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_triage)

    s = sub.add_parser("serve", help="start the REST API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args) or 0
    except StoreError as e:
        print(f"devtrack: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
