import math

from gauntlet.cli import main
from gauntlet.runner import CaseResult, write_results
from gauntlet.summary import summarize, to_markdown


def _r(cid, suite, score, flags=(), error=None, split="holdout", latency=100.0):
    return CaseResult(cid, suite, split, suite == "security", "rel_x", score, latency,
                      400, 20, 0.0001, error, "out", tuple(flags))  # fmt: skip


RESULTS = [
    _r("q1", "quality", 1.0, latency=50),
    _r("q2", "quality", 0.5, latency=150),
    _r("q3", "quality", 1.0, split="dev"),
    _r("q4", "quality", 0.0, error="HTTP 500"),
    _r("s1", "security", 1.0, flags=("prompt_injection", "canary_leak")),
    _r("s2", "security", 1.0),
]


def test_summarize_counts_only_what_happened():
    s = summarize(RESULTS)
    assert s["cases"] == 6 and s["errors"] == 1
    assert s["quality_n"] == 2 and s["quality_exact"] == 1
    assert math.isclose(s["quality_mean_f1"], 0.75)
    assert s["security_n"] == 2 and s["raw_leak_attempts"] == 1 and s["served_leaks"] == 0
    assert s["detector_flagged"] == 1
    assert s["latency_p95_ms"] == 150


def test_markdown_and_empty_cases():
    md = to_markdown({"a": summarize(RESULTS), "b": summarize([])})
    assert "| holdout exact match | 1/2 (50.0%" in md and "n/a" in md


def test_summarize_cli(tmp_path, capsys):
    p = tmp_path / "r.jsonl"
    write_results(p, RESULTS)
    out, js = tmp_path / "s.md", tmp_path / "s.json"
    assert main(["summarize", "--run", f"m={p}", "--out", str(out), "--json", str(js)]) == 0
    assert out.read_text().startswith("| metric | m |") and js.exists()
    assert main(["summarize", "--run", "nopath"]) == 2
    capsys.readouterr()
