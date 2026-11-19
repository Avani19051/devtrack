import pytest
from fastapi.testclient import TestClient

from devtrack.api import create_app
from devtrack.store import Repository


@pytest.fixture
def client(tmp_path):
    Repository.init(tmp_path).close()
    return TestClient(create_app(tmp_path))


def upload(client, path, content, message="msg", **extra):
    return client.post("/artifacts", data={"path": path, "message": message, **extra},
                       files={"file": (path, content)})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_upload_history_diff_content(client):
    assert upload(client, "rtl/alu.v", b"module alu;\nendmodule\n").status_code == 201
    r = upload(client, "rtl/alu.v", b"module alu;\n  input a;\nendmodule\n", "add port")
    assert r.json()["number"] == 2

    hist = client.get("/artifacts/rtl/alu.v/versions").json()
    assert [v["message"] for v in hist] == ["msg", "add port"]

    d = client.get("/artifacts/rtl/alu.v/diff", params={"old": 1}).json()
    assert d["added"] == 1 and d["removed"] == 0

    body = client.get("/artifacts/rtl/alu.v/versions/1/content").content
    assert body == b"module alu;\nendmodule\n"

    assert client.get("/artifacts").json()[0]["latest"] == 2


def test_unchanged_upload(client):
    upload(client, "a.txt", b"x\n")
    assert upload(client, "a.txt", b"x\n").json() == {"path": "a.txt", "unchanged": True}


def test_strict_upload_rejected(client):
    r = upload(client, "cfg.json", b'{"name": "x"}\n', strict="true")
    assert r.status_code == 400 and "failed validation" in r.json()["detail"]


@pytest.mark.parametrize("path", ["../escape.txt", ".devtrack/metadata.db"])
def test_upload_path_safety(client, path):
    assert upload(client, path, b"x\n").status_code == 400


def test_404s(client):
    assert client.get("/artifacts/nope.txt/versions").status_code == 404
    upload(client, "a.txt", b"x\n")
    assert client.get("/artifacts/a.txt/versions/7").status_code == 404


def test_validate_dry_run(client):
    r = client.post("/validate", files={"file": ("Bad Name.txt", b"password=1\n")})
    body = r.json()
    assert body["passed"] is False
    assert {i["rule"] for i in body["issues"]} == {"name_pattern", "forbid"}
    assert client.get("/artifacts").json() == []


def test_triage_endpoint(client):
    r = client.post("/triage", json={"log": "[  FAILED  ] Store.Lock (12 ms)\n"
                                            "sqlite3.OperationalError: database is locked\n"})
    assert r.json()[0]["matches"][0]["id"] == "KI-007"


def test_verify_endpoint(client):
    upload(client, "a.txt", b"x\n")
    assert client.get("/verify").json() == {"ok": True, "problems": []}
