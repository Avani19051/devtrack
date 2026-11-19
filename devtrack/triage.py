"""AI-assisted triage of failing test logs.

1. Parse pytest / ctest / GoogleTest output into individual failures.
2. Retrieve the most similar known issues from a small knowledge base using TF-IDF
   cosine similarity (the "retrieval" half of RAG; pure Python, no dependencies).
3. Optionally send the failure + retrieved context to an LLM for a summary.
   Enabled only when DEVTRACK_LLM_API_KEY is set; works with any OpenAI-compatible
   chat endpoint (DEVTRACK_LLM_URL, DEVTRACK_LLM_MODEL). Without a key the tool stays
   fully offline and reports the retrieved matches.
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KB = Path(__file__).resolve().parent.parent / "rules" / "known_issues.json"

_FAIL_PATTERNS = [
    re.compile(r"^FAILED (?P<name>\S+)(?: - (?P<msg>.*))?$"),              # pytest summary
    re.compile(r"^\[  FAILED  \] (?P<name>\S+?)(?: \(\d+ ms\))?$"),          # GoogleTest
    re.compile(r"^\s*\d+ - (?P<name>\S+) \((?P<msg>Failed|SEGFAULT|Timeout)\)$"),  # ctest
]
_ERROR_LINE = re.compile(r"^(E\s+.*|.*(Error|Exception|error:|Failure|Assertion).*)$")


@dataclass
class Failure:
    test: str
    message: str
    context: str  # error lines near the failure

    @property
    def text(self) -> str:
        return f"{self.test} {self.message} {self.context}"


def parse_failures(log: str) -> list[Failure]:
    lines = log.splitlines()
    error_lines = [l.strip() for l in lines if _ERROR_LINE.match(l.strip())]
    failures: dict[str, Failure] = {}
    for line in lines:
        for pat in _FAIL_PATTERNS:
            m = pat.match(line.rstrip())
            if m:
                name = m.group("name")
                msg = (m.groupdict().get("msg") or "").strip()
                if name not in failures:
                    failures[name] = Failure(name, msg, " ".join(error_lines[-5:]))
                break
    if not failures and error_lines:  # unstructured log: treat it as one failure
        failures["log"] = Failure("log", error_lines[0], " ".join(error_lines[:5]))
    return list(failures.values())


# ---------------------------------------------------------------- retrieval

def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z_][a-z0-9_]+", text.lower()) if len(t) > 2]


class KnowledgeBase:
    def __init__(self, entries: list[dict]):
        self.entries = entries
        docs = [_tokens(e["title"] + " " + " ".join(e.get("signatures", [])) + " " +
                        e.get("cause", "")) for e in entries]
        n = len(docs)
        df = Counter(t for d in docs for t in set(d))
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.vectors = [self._vec(d) for d in docs]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_KB) -> "KnowledgeBase":
        return cls(json.loads(Path(path).read_text()))

    def _vec(self, tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        v = {t: c * self.idf.get(t, 0.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def search(self, query: str, k: int = 2, min_score: float = 0.1) -> list[tuple[float, dict]]:
        q = self._vec(_tokens(query))
        scored = [(sum(q.get(t, 0) * w for t, w in vec.items()), e)
                  for vec, e in zip(self.vectors, self.entries)]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(round(s, 3), e) for s, e in scored[:k] if s >= min_score]


# ---------------------------------------------------------------- optional LLM

def llm_summary(failure: Failure, matches: list[tuple[float, dict]]) -> str | None:
    key = os.environ.get("DEVTRACK_LLM_API_KEY")
    if not key:
        return None
    url = os.environ.get("DEVTRACK_LLM_URL", "https://api.openai.com/v1/chat/completions")
    model = os.environ.get("DEVTRACK_LLM_MODEL", "gpt-4o-mini")
    known = "\n".join(f"- {e['title']}: cause={e['cause']}; fix={e['fix']}" for _, e in matches)
    prompt = (
        "You are helping debug a failing regression test.\n"
        f"Test: {failure.test}\nMessage: {failure.message}\nLog excerpt: {failure.context}\n"
        f"Similar known issues:\n{known or '- none'}\n"
        "In at most 3 sentences: the most likely root cause and the first thing to check."
    )
    body = json.dumps({"model": model, "temperature": 0,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json",
                                             "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)["choices"][0]["message"]["content"].strip()
    except Exception as e:  # never let the optional LLM break triage
        return f"(LLM unavailable: {e.__class__.__name__})"


def triage(log: str, kb: KnowledgeBase | None = None) -> list[dict]:
    kb = kb or KnowledgeBase.load()
    report = []
    for f in parse_failures(log):
        matches = kb.search(f.text)
        report.append({
            "test": f.test,
            "message": f.message,
            "matches": [{"score": s, "id": e["id"], "title": e["title"],
                         "cause": e["cause"], "fix": e["fix"]} for s, e in matches],
            "llm_summary": llm_summary(f, matches),
        })
    return report


def format_report(report: list[dict]) -> str:
    if not report:
        return "No failures found."
    out = []
    for r in report:
        out.append(f"✗ {r['test']}" + (f"  ({r['message']})" if r["message"] else ""))
        if r["matches"]:
            best = r["matches"][0]
            out.append(f"   likely: {best['title']} [{best['id']}, score {best['score']}]")
            out.append(f"   cause:  {best['cause']}")
            out.append(f"   fix:    {best['fix']}")
        else:
            out.append("   no similar known issue: add one to rules/known_issues.json")
        if r["llm_summary"]:
            out.append(f"   LLM:    {r['llm_summary']}")
    return "\n".join(out)
