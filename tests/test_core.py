"""Hash / diff / validate behave the same on the C++ and Python backends."""
import hashlib

import pytest

from devtrack.core import Core, CoreError, diff_stats, find_core_binary, parse_rules

RULES = (
    "name_pattern=^[a-z0-9_]+(\\.[a-z0-9]+)+$\n"
    "required_keys.json=name,version\n"
    "forbid=password=\n"
    "no_trailing_whitespace=true\n"
)


def test_hash_matches_hashlib(core, tmp_path):
    p = tmp_path / "blob.bin"
    data = bytes(range(256)) * 300  # multi-block, includes NUL bytes
    p.write_bytes(data)
    assert core.hash_file(p) == hashlib.sha256(data).hexdigest()


def test_diff_reports_changes(core, write):
    a = write("a.txt", "one\ntwo\nthree\n")
    b = write("b.txt", "one\nthree\nfour\n")
    text = core.diff_files(a, b)
    assert diff_stats(text) == (1, 1)
    assert "-two" in text and "+four" in text


def test_diff_identical_files(core, write):
    a = write("a.txt", "same\n")
    b = write("b.txt", "same\n")
    assert diff_stats(core.diff_files(a, b)) == (0, 0)


def test_validate_clean(core, write):
    rules = write("r.rules", RULES)
    f = write("ip_block.json", '{"name": "alu", "version": 3}\n')
    assert core.validate_file(f, rules) == []


def test_validate_reports_all_issues(core, write):
    rules = write("r.rules", RULES)
    f = write("Bad-Name.json", '{"name": "x"} \npassword=hunter2\n')
    found = {(i.rule, i.line) for i in core.validate_file(f, rules)}
    assert found == {("name_pattern", 0), ("required_keys", 0),
                     ("no_trailing_whitespace", 1), ("forbid", 2)}


def test_bad_rules_file_raises(core, write):
    rules = write("r.rules", "colour=blue\n")
    f = write("x.txt", "hi\n")
    with pytest.raises(CoreError):
        core.validate_file(f, rules)


def test_parse_rules_python():
    r = parse_rules(RULES + "max_size_kb=10\n")
    assert r.required_keys["json"] == ["name", "version"]
    assert r.max_size_kb == 10


@pytest.mark.skipif(not find_core_binary(), reason="C++ core not built")
def test_backends_agree(write):
    rules = write("r.rules", RULES)
    f = write("Odd Name.json", '{"version": 1}\t\napi_key=1\npassword=2\n')
    cpp = Core(find_core_binary()).validate_file(f, rules)
    py = Core(None).validate_file(f, rules)
    assert [i.to_dict() for i in cpp] == [i.to_dict() for i in py]
