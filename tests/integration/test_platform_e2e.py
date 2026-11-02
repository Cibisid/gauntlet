"""Full-platform test through real sockets: mock model + proxy server + every CLI command.

Human labels are SIMULATED here from ground truth so the judge workflow can be
tested; real qualification needs real human labels (judges/qualifications/README).
"""

import json
import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from gauntlet import mock_server
from gauntlet.cases import Case, load_cases, select, write_cases
from gauntlet.cli import main
from gauntlet.proxy import Settings, create_app, hash_key
from gauntlet.runner import read_results

ROOT = Path(__file__).resolve().parents[2]
REL = ROOT / "releases" / "trialbridge"
CASES = ROOT / "cases" / "trialbridge" / "synthetic_v1.jsonl"
ADMIN = "admin-key-integration-0123456789"
CLIENT = "client-key-integration-012345678"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    os.environ["MOCK_LATENCY_SCALE"] = "0"
    mock = mock_server.make_server("127.0.0.1", 0)
    threading.Thread(target=mock.serve_forever, daemon=True).start()
    mock_url = f"http://127.0.0.1:{mock.server_address[1]}/v1"

    state = tmp_path_factory.mktemp("state")
    settings = Settings(
        upstream_base_url=mock_url,
        state_dir=state,
        api_keys={"ci": hash_key(CLIENT)},
        admin_key_hash=hash_key(ADMIN),
        rate_limit_rpm=1_000_000,  # the bench test measures throughput, not the limiter
    )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port,
                                           log_level="warning"))  # fmt: skip
    threading.Thread(target=server.run, daemon=True).start()
    proxy_url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{proxy_url}/healthz").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    os.environ["GAUNTLET_ADMIN_KEY"] = ADMIN
    os.environ["GAUNTLET_API_KEY"] = CLIENT
    yield {"mock": mock_url, "proxy": proxy_url, "state": state}
    server.should_exit = True
    mock.shutdown()


def test_rollout_via_cli_over_http(stack, capsys):
    proxy = stack["proxy"]
    assert (
        main(["rollout", "deploy", "--proxy", proxy, "--release", str(REL / "baseline.yaml")]) == 0
    )
    assert main(["rollout", "start", "--proxy", proxy,
                 "--release", str(REL / "examples/injectable_model_guarded.yaml")]) == 0  # fmt: skip
    cases = load_cases(CASES)
    inputs = [dict(c.inputs) for c in select(cases, suite="security")]
    with httpx.Client(base_url=proxy, headers={"Authorization": f"Bearer {CLIENT}"}) as c:
        for i in range(300):
            c.post("/v1/apps/trialbridge/invoke", json={"inputs": inputs[i % len(inputs)]})
    rc = main(["rollout", "watch", "--proxy", proxy, "--interval", "0", "--timeout", "5",
               "--release", str(REL / "examples/injectable_model_guarded.yaml")])  # fmt: skip
    out = capsys.readouterr().out
    assert rc == 1 and "rollback" in out and "leak" in out
    assert main(["rollout", "status", "--proxy", proxy]) == 0
    assert main(["audit-verify", str(stack["state"] / "audit.jsonl")]) == 0

    # healthy candidate: start, tick, manual promote, then nothing left to roll back
    assert (
        main(["rollout", "start", "--proxy", proxy, "--release", str(REL / "candidate.yaml")]) == 0
    )
    assert (
        main(["rollout", "tick", "--proxy", proxy, "--release", str(REL / "candidate.yaml")]) == 0
    )
    assert main(["rollout", "promote", "--proxy", proxy]) == 0
    assert (
        main(["rollout", "start", "--proxy", proxy, "--release", str(REL / "baseline.yaml")]) == 0
    )
    assert main(["rollout", "rollback", "--proxy", proxy, "--reason", "test"]) == 0


def test_bench_triage_drift_via_cli(stack, tmp_path, capsys):
    proxy = stack["proxy"]
    main(["rollout", "deploy", "--proxy", proxy, "--release", str(REL / "baseline.yaml")])
    out = tmp_path / "bench.json"
    assert main(["bench", "--url", proxy, "--cases", str(CASES), "--levels", "1,4",
                 "--duration", "0.5", "--out", str(out), "--note", "mock upstream"]) == 0  # fmt: skip
    report = json.loads(out.read_text())
    assert report["levels"][1]["requests"] > 0 and report["levels"][1]["errors"] == 0
    traces = stack["state"] / "traces.jsonl"
    fb = stack["state"] / "feedback.jsonl"
    fb.write_text("")
    assert main(["triage", "--traces", str(traces), "--feedback", str(fb),
                 "--out", str(tmp_path / "triaged.jsonl")]) == 0  # fmt: skip
    assert main(["drift", "--reference", str(traces), "--current", str(traces)]) == 0
    capsys.readouterr()


def test_judge_label_qualify_flow(stack, tmp_path, monkeypatch, capsys):
    base = stack["mock"]
    rubric = ROOT / "judges" / "rubrics" / "eligibility.yaml"
    results = tmp_path / "res.jsonl"
    assert main(["run", "--release", str(REL / "examples/cheaper_model.yaml"), "--cases", str(CASES),
                 "--base-url", base, "--out", str(results), "--concurrency", "16"]) == 0  # fmt: skip
    cases = {c.id: c for c in load_cases(CASES)}
    res = [r for r in read_results(results) if r.suite == "quality"]

    # Simulated human labels from ground truth (see module docstring).
    labels = tmp_path / "labels.jsonl"
    with labels.open("w") as fh:
        for r in res[:300]:
            fh.write(json.dumps({"case_id": r.case_id, "release_id": r.release_id,
                                 "label": "pass" if r.score == 1.0 else "fail",
                                 "labeler": "simulated"}) + "\n")  # fmt: skip
    qdir = tmp_path / "quals"
    rc = main(["qualify", "--rubric", str(rubric), "--labels", str(labels), "--results", str(results),
               "--cases", str(CASES), "--base-url", base, "--out-dir", str(qdir)])  # fmt: skip
    assert rc == 0 and "QUALIFIED" in capsys.readouterr().out

    judged_cases = tmp_path / "judged.jsonl"
    picked = [cases[r.case_id] for r in res[:30]]
    write_cases(judged_cases, [Case(c.id, c.suite, c.split, c.inputs, c.expected, "judge:eligibility")
                               for c in picked] + list(select(load_cases(CASES), suite="security"))[:2])  # fmt: skip
    out = tmp_path / "judged_res.jsonl"
    assert main(["run", "--release", str(REL / "baseline.yaml"), "--cases", str(judged_cases),
                 "--base-url", base, "--out", str(out), "--judge-rubric", str(rubric),
                 "--qualifications", str(qdir)]) == 0  # fmt: skip
    assert all(r.error is None for r in read_results(out))
    assert main(["run", "--release", str(REL / "baseline.yaml"), "--cases", str(judged_cases),
                 "--base-url", base, "--out", str(out), "--judge-rubric", str(rubric),
                 "--qualifications", str(tmp_path / "none")]) == 2  # fmt: skip

    # interactive labelling + inter-annotator agreement
    answers = iter(["p", "", "f", "", "q"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    a = tmp_path / "a.jsonl"
    assert main(["label", "--results", str(results), "--cases", str(CASES), "--out", str(a),
                 "--labeler", "me", "--n", "5"]) == 0  # fmt: skip
    assert main(["agreement", str(a), str(a)]) == 0
    assert main(["guardrail-eval", "--cases", str(CASES)]) == 0
    assert "recall" in capsys.readouterr().out


def test_hash_key_cli(monkeypatch, capsys):
    monkeypatch.setenv("GAUNTLET_KEY_TO_HASH", "short")
    assert main(["hash-key"]) == 2
    monkeypatch.setenv("GAUNTLET_KEY_TO_HASH", "a-sufficiently-long-key-1234567")
    assert main(["hash-key"]) == 0
    assert capsys.readouterr().out.startswith("scrypt$")
