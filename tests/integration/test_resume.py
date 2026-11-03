"""Resumable runs: a daily quota stops a run part-way; the next run finishes it."""

import threading
from pathlib import Path

from gauntlet import mock_server
from gauntlet.cli import main
from gauntlet.runner import read_results, write_results

ROOT = Path(__file__).resolve().parents[2]
REL = ROOT / "releases" / "trialbridge" / "baseline.yaml"
CASES = ROOT / "cases" / "trialbridge" / "synthetic_v1.jsonl"


def test_limit_then_resume_completes_gate_cases(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MOCK_LATENCY_SCALE", "0")
    srv = mock_server.make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    out = tmp_path / "r.jsonl"
    base = ["run", "--release", str(REL), "--cases", str(CASES), "--base-url", url,
            "--out", str(out), "--gate-cases-only", "--resume", "--concurrency", "8"]  # fmt: skip
    try:
        assert main([*base, "--limit", "100"]) == 0
        assert len(read_results(out)) == 100
        # simulate a quota error on one stored result: it must be re-run, not kept
        rows = read_results(out)
        rows[0] = rows[0].__class__(**{**rows[0].__dict__, "error": "quota exhausted"})
        write_results(out, rows)
        assert main(base) == 0
    finally:
        srv.shutdown()
    final = read_results(out)
    assert len(final) == 514 and len({r.case_id for r in final}) == 514
    assert not any(r.error for r in final)
    assert all(r.suite == "security" or r.split == "holdout" for r in final)
    assert "complete: 514/514" in capsys.readouterr().out
