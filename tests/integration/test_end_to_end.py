"""End-to-end: real HTTP server, real CLI, the committed releases and case set.

These tests prove the gate reaches the expected verdict for each example
release. If a change to the gate or scorers flips a verdict, CI fails.
"""

import json
import shutil
import threading
from pathlib import Path

import httpx
import pytest

from gauntlet import mock_server
from gauntlet.cli import main

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "cases" / "trialbridge" / "synthetic_v1.jsonl"
RELEASES = ROOT / "releases" / "trialbridge"


@pytest.fixture(scope="module")
def mock_url():
    import os

    os.environ["MOCK_LATENCY_SCALE"] = "0"
    server = mock_server.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def baseline_results(mock_url, tmp_path_factory):
    out = tmp_path_factory.mktemp("runs") / "baseline.jsonl"
    rc = main(
        [
            "run",
            "--release",
            str(RELEASES / "baseline.yaml"),
            "--cases",
            str(CASES),
            "--base-url",
            mock_url,
            "--out",
            str(out),
            "--concurrency",
            "16",
        ]
    )
    assert rc == 0
    return out


@pytest.mark.parametrize(
    ("release", "expected_rc", "failing_check"),
    [
        ("examples/reworded_prompt.yaml", 0, None),
        ("examples/cheaper_model.yaml", 1, "Quality non-inferiority"),
        ("examples/injectable_model.yaml", 1, "Security packs"),
        ("candidate.yaml", 0, None),
    ],
)
def test_gate_verdicts(mock_url, baseline_results, tmp_path, release, expected_rc, failing_check):
    cand = tmp_path / "cand.jsonl"
    report = tmp_path / "report.md"
    assert (
        main(
            [
                "run",
                "--release",
                str(RELEASES / release),
                "--cases",
                str(CASES),
                "--base-url",
                mock_url,
                "--out",
                str(cand),
                "--concurrency",
                "16",
            ]
        )
        == 0
    )
    rc = main(
        [
            "gate",
            "--baseline",
            str(baseline_results),
            "--candidate",
            str(cand),
            "--release",
            str(RELEASES / release),
            "--report",
            str(report),
        ]
    )
    assert rc == expected_rc
    text = report.read_text()
    if failing_check:
        assert f"| {failing_check}" in text
        line = next(ln for ln in text.splitlines() if ln.startswith(f"| {failing_check}"))
        assert "**FAIL**" in line


def test_cli_id_and_gate_input_error(tmp_path, capsys):
    assert main(["id", str(RELEASES / "baseline.yaml")]) == 0
    assert capsys.readouterr().out.startswith("rel_")
    empty = tmp_path / "e.jsonl"
    empty.write_text(
        json.dumps(
            {
                "case_id": "x",
                "suite": "security",
                "split": "holdout",
                "critical": True,
                "release_id": "r",
                "score": 1.0,
                "latency_ms": 1.0,
                "input_tokens": 1,
                "output_tokens": 1,
                "cost_usd": 0.0,
                "error": None,
                "output": "",
            }
        )
        + "\n"
    )
    assert (
        main(
            [
                "gate",
                "--baseline",
                str(empty),
                "--candidate",
                str(empty),
                "--release",
                str(RELEASES / "baseline.yaml"),
            ]
        )
        == 2
    )


def test_mock_server_contract(mock_url):
    """The mock must speak the OpenAI chat-completions shape the provider expects."""
    base = mock_url.removesuffix("/v1")
    assert httpx.get(f"{base}/healthz").json() == {"status": "ok"}
    models = {m["id"] for m in httpx.get(f"{mock_url}/models").json()["data"]}
    assert {"mock-accurate", "mock-sloppy", "mock-obedient"} <= models
    r = httpx.post(
        f"{mock_url}/chat/completions",
        json={"model": "mock-accurate", "messages": [{"role": "user", "content": "hi"}]},
    )
    body = r.json()
    assert r.status_code == 200
    assert body["object"] == "chat.completion"
    assert isinstance(body["choices"][0]["message"]["content"], str)
    assert {"prompt_tokens", "completion_tokens", "total_tokens"} <= body["usage"].keys()
    assert (
        httpx.post(
            f"{mock_url}/chat/completions", json={"model": "nope", "messages": []}
        ).status_code
        == 404
    )
    assert httpx.post(f"{mock_url}/chat/completions", content=b"{bad").status_code == 400
    assert httpx.get(f"{base}/nope").status_code == 404
    assert httpx.post(f"{base}/nope", json={}).status_code == 404


def test_mock_server_auth_and_flaky(mock_url, monkeypatch):
    monkeypatch.setenv("MOCK_API_KEY", "k1")
    url = f"{mock_url}/chat/completions"
    body = {"model": "mock-flaky", "messages": [{"role": "user", "content": "hi"}]}
    assert httpx.post(url, json=body).status_code == 401
    codes = {
        httpx.post(url, json=body, headers={"Authorization": "Bearer k1"}).status_code
        for _ in range(4)
    }
    assert codes == {200, 503}


def test_flaky_model_is_absorbed_by_retries(mock_url, tmp_path):
    release = (
        (RELEASES / "baseline.yaml").read_text().replace("name: mock-accurate", "name: mock-flaky")
    )
    rel = tmp_path / "flaky.yaml"
    rel.write_text(release)
    few = tmp_path / "few.jsonl"
    few.write_text("".join(CASES.read_text().splitlines(keepends=True)[:4]))
    out = tmp_path / "flaky.jsonl"
    assert (
        main(
            [
                "run",
                "--release",
                str(rel),
                "--cases",
                str(few),
                "--base-url",
                mock_url,
                "--out",
                str(out),
                "--concurrency",
                "1",
            ]
        )
        == 0
    )
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert sum(1 for r in rows if r["error"]) == 0


def test_example_files_present():
    assert CASES.exists()
    assert shutil.which("python") or shutil.which("python3")
