import pytest

from devtrack.store import Repository, StoreError, find_root


def test_init_twice_fails(repo):
    with pytest.raises(StoreError, match="already initialised"):
        Repository.init(repo.root)


def test_find_root_from_subdir(repo):
    sub = repo.root / "a" / "b"
    sub.mkdir(parents=True)
    assert find_root(sub) == repo.root


def test_add_creates_versions(repo, write):
    write("alu_config.json", '{"name": "alu", "version": 1}\n')
    v1 = repo.add("alu_config.json", "first", author="avani")
    assert (v1.number, v1.status, v1.author) == (1, "passed", "avani")

    write("alu_config.json", '{"name": "alu", "version": 2}\n')
    v2 = repo.add("alu_config.json", "bump")
    assert v2.number == 2
    assert [v.message for v in repo.history("alu_config.json")] == ["first", "bump"]


def test_unchanged_content_is_skipped(repo, write):
    write("notes.txt", "hello\n")
    assert repo.add("notes.txt", "one") is not None
    assert repo.add("notes.txt", "again") is None
    assert len(repo.history("notes.txt")) == 1


def test_identical_content_stored_once(repo, write):
    write("a.txt", "shared\n")
    write("b.txt", "shared\n")
    va, vb = repo.add("a.txt", "a"), repo.add("b.txt", "b")
    assert va.sha256 == vb.sha256
    objects = [p for p in (repo.dt / "objects").rglob("*") if p.is_file()]
    assert len(objects) == 1


def test_failed_validation_is_recorded(repo, write):
    write("config.json", '{"name": "x"}\n')  # missing "version"
    v = repo.add("config.json", "oops")
    assert v.status == "failed"
    assert [i.rule for i in v.issues] == ["required_keys"]
    # issues are persisted, not just returned
    assert repo.get_version("config.json", 1).issues[0].rule == "required_keys"


def test_strict_mode_rejects(repo, write):
    write("config.json", '{"name": "x"}\n')
    with pytest.raises(StoreError, match="failed validation"):
        repo.add("config.json", "oops", strict=True)
    assert repo.list_artifacts() == []


def test_diff_between_versions(repo, write):
    write("top.v", "module top;\nendmodule\n")
    repo.add("top.v", "v1")
    write("top.v", "module top;\n  wire clk;\nendmodule\n")
    repo.add("top.v", "v2")
    d = repo.diff("top.v", 1)
    assert (d["old"], d["new"], d["added"], d["removed"]) == (1, 2, 1, 0)
    assert "+  wire clk;" in d["diff"]


def test_checkout_restores_old_version(repo, write):
    p = write("top.v", "old\n")
    repo.add("top.v", "v1")
    p.write_text("new\n")
    repo.add("top.v", "v2")
    repo.checkout("top.v", 1)
    assert p.read_text() == "old\n"
    assert repo.read("top.v").decode() == "new\n"  # store still has v2 as latest


def test_list_artifacts_shows_latest(repo, write):
    write("a.txt", "1\n"); repo.add("a.txt", "a1")
    write("a.txt", "2\n"); repo.add("a.txt", "a2")
    write("b.txt", "1\n"); repo.add("b.txt", "b1")
    rows = {r["path"]: r["latest"] for r in repo.list_artifacts()}
    assert rows == {"a.txt": 2, "b.txt": 1}


def test_verify_detects_corruption(repo, write):
    write("a.txt", "data\n")
    v = repo.add("a.txt", "a")
    assert repo.verify() == []
    obj = repo.dt / "objects" / v.sha256[:2] / v.sha256[2:]
    obj.write_text("tampered\n")
    assert repo.verify() == [f"corrupted object {v.sha256}"]


@pytest.mark.parametrize("bad", ["../outside.txt", "/etc/passwd"])
def test_paths_outside_project_rejected(repo, bad):
    with pytest.raises(StoreError):
        repo.add(bad, "nope")


def test_errors_for_untracked_and_missing_version(repo, write):
    with pytest.raises(StoreError, match="not tracked"):
        repo.history("ghost.txt")
    write("a.txt", "x\n"); repo.add("a.txt", "a")
    with pytest.raises(StoreError, match="no version 9"):
        repo.get_version("a.txt", 9)
