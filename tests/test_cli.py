"""End-to-end tests through the command-line interface."""
import json

import pytest

from devtrack.cli import main


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    return tmp_path


def test_full_workflow(project, capsys):
    (project / "fifo_cfg.json").write_text('{"name": "fifo", "version": 1, "depth": 16}\n')
    assert main(["add", "fifo_cfg.json", "-m", "initial", "--author", "avani"]) == 0
    (project / "fifo_cfg.json").write_text('{"name": "fifo", "version": 2, "depth": 32}\n')
    assert main(["add", "fifo_cfg.json", "-m", "deeper fifo"]) == 0
    capsys.readouterr()

    assert main(["ls", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["path"] == "fifo_cfg.json" and rows[0]["latest"] == 2

    assert main(["diff", "fifo_cfg.json", "1"]) == 0
    out = capsys.readouterr().out
    assert "(+1 -1)" in out and '"depth": 32' in out

    assert main(["checkout", "fifo_cfg.json", "1"]) == 0
    assert '"depth": 16' in (project / "fifo_cfg.json").read_text()

    assert main(["verify"]) == 0


def test_add_returns_nonzero_on_validation_failure(project, capsys):
    (project / "BadName.txt").write_text("ok\n")
    assert main(["add", "BadName.txt", "-m", "x"]) == 1
    assert "name_pattern" in capsys.readouterr().out


def test_strict_add_rejects(project, capsys):
    (project / "creds.txt").write_text("password=1234\n")
    assert main(["add", "creds.txt", "-m", "x", "--strict"]) == 1
    assert "rejected" in capsys.readouterr().err


def test_validate_without_storing(project, capsys):
    (project / "good_file.yaml").write_text("name: alu\nversion: 1\n")
    assert main(["validate", "good_file.yaml"]) == 0
    assert "PASS" in capsys.readouterr().out
    assert main(["ls"]) == 0
    assert "no artifacts" in capsys.readouterr().out


def test_commands_outside_project_fail(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["ls"]) == 2
    assert "not a DevTrack project" in capsys.readouterr().err


def test_triage_from_file(project, capsys):
    log = project / "run.log"
    log.write_text("FAILED tests/test_x.py::test_seg - Segmentation fault (core dumped)\n")
    assert main(["triage", str(log)]) == 0
    out = capsys.readouterr().out
    assert "test_seg" in out and "KI-005" in out
