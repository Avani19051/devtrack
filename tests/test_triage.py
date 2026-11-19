import pytest

from devtrack.triage import KnowledgeBase, format_report, parse_failures, triage

PYTEST_LOG = """\
============================= FAILURES =============================
E       AssertionError: expected 32 but got 31
E       assert 31 == 32
=========================== short test summary info ===========================
FAILED tests/test_fifo.py::test_depth - AssertionError: expected 32 but got 31
FAILED tests/test_io.py::test_load - FileNotFoundError: No such file 'cfg.json'
"""

GTEST_LOG = """\
[ RUN      ] Sha256.Abc
core/tests/test_core.cpp:20: Failure
Expected equality of these values:
[  FAILED  ] Sha256.Abc (0 ms)
"""

CTEST_LOG = """\
The following tests FAILED:
\t  3 - Parser.Huge (SEGFAULT)
"""


def test_parse_pytest():
    fails = parse_failures(PYTEST_LOG)
    assert [f.test for f in fails] == ["tests/test_fifo.py::test_depth",
                                       "tests/test_io.py::test_load"]
    assert "FileNotFoundError" in fails[1].message


def test_parse_gtest_and_ctest():
    assert [f.test for f in parse_failures(GTEST_LOG)] == ["Sha256.Abc"]
    f = parse_failures(CTEST_LOG)[0]
    assert (f.test, f.message) == ("Parser.Huge", "SEGFAULT")


def test_unstructured_log_still_triaged():
    fails = parse_failures("something broke\nRuntimeError: database is locked\n")
    assert len(fails) == 1 and fails[0].test == "log"


def test_clean_log_has_no_failures():
    assert parse_failures("===== 12 passed in 0.3s =====\n") == []
    assert format_report([]) == "No failures found."


@pytest.mark.parametrize("log,expected", [
    (PYTEST_LOG, ["KI-004", "KI-003"]),
    (CTEST_LOG, ["KI-005"]),
    ("FAILED t::test_x - TimeoutExpired: timed out after 30s\n", ["KI-006"]),
    ("FAILED t::test_y - corrupted object abc: hash mismatch\n", ["KI-002"]),
])
def test_retrieval_picks_right_known_issue(log, expected, monkeypatch):
    monkeypatch.delenv("DEVTRACK_LLM_API_KEY", raising=False)
    report = triage(log)
    assert [r["matches"][0]["id"] for r in report] == expected
    assert all(r["llm_summary"] is None for r in report)  # offline by default


def test_no_match_below_threshold():
    kb = KnowledgeBase([{"id": "X", "title": "alpha beta", "signatures": [],
                         "cause": "gamma", "fix": "delta"}])
    assert kb.search("completely unrelated words here") == []


def test_llm_failure_does_not_break_triage(monkeypatch):
    monkeypatch.setenv("DEVTRACK_LLM_API_KEY", "dummy")
    monkeypatch.setenv("DEVTRACK_LLM_URL", "http://127.0.0.1:9/unreachable")
    report = triage(CTEST_LOG)
    assert report[0]["llm_summary"].startswith("(LLM unavailable")
