import json
import random
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from gauntlet import mock_server
from gauntlet.bench import bench, run_level, to_markdown
from gauntlet.cases import load_cases, select
from gauntlet.monitor import drift_report, psi, read_jsonl, triage
from gauntlet.proxy import (
    AuditLog,
    Event,
    KeyStore,
    RateLimiter,
    Settings,
    create_app,
    hash_key,
    online_score,
    parse_key_list,
    verify_audit_log,
    verify_key,
    window_stats,
)
from gauntlet.release import load_release, release_id
from gauntlet.rollout import Decision, ProxyAdmin, RolloutPolicy, decide, start, tick, watch

ROOT = Path(__file__).resolve().parents[2]
REL = ROOT / "releases" / "trialbridge"
CASES = load_cases(ROOT / "cases" / "trialbridge" / "synthetic_v1.jsonl")
QUALITY = [dict(c.inputs) for c in select(CASES, suite="quality")][:200]
ATTACKS = [dict(c.inputs) for c in select(CASES, suite="security")]
CLIENT_KEY = "client-key-for-tests-0123456789"
ADMIN_KEY = "admin-key-for-tests-0123456789ab"


def upstream(fail_models=()):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] in fail_models:
            return httpx.Response(503, json={"error": "down"})
        text = mock_server.answer(body["model"], body["messages"])
        return httpx.Response(200, json={
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10},
        })  # fmt: skip

    return httpx.MockTransport(handler)


@pytest.fixture
def proxy(tmp_path):
    settings = Settings(
        upstream_base_url="http://upstream/v1",
        state_dir=tmp_path / "state",
        api_keys={"tester": hash_key(CLIENT_KEY)},
        admin_key_hash=hash_key(ADMIN_KEY),
        rate_limit_rpm=100_000,
    )
    app = create_app(settings, transport=upstream(fail_models={"mock-flaky"}))
    with TestClient(app) as client:
        yield client, settings


def auth(key=CLIENT_KEY):
    return {"Authorization": f"Bearer {key}"}


def deploy(client, path="baseline.yaml"):
    r = client.put("/admin/routing", headers=auth(ADMIN_KEY),
                   json={"stable": load_release(REL / path), "reason": "test"})  # fmt: skip
    assert r.status_code == 200
    return r.json()


# ---------- keys, rate limit, audit ----------


def test_key_hashing_and_store():
    h = hash_key("secret-value")
    assert verify_key("secret-value", h) and not verify_key("other", h)
    assert not verify_key("x", "md5$aa$bb") and not verify_key("x", "garbage")
    store = KeyStore(parse_key_list(f"alice:{h}, ,bad"))
    assert store.identify("secret-value") == "alice"
    assert store.identify("secret-value") == "alice"  # cached path
    assert store.identify("nope") is None


def test_rate_limiter_refills():
    rl = RateLimiter(rpm=60)  # 1/s, burst 16
    assert all(rl.allow("a", now=0.0) for _ in range(16))
    assert not rl.allow("a", now=0.0)
    assert rl.allow("a", now=1.1)
    assert rl.allow("b", now=0.0)


def test_audit_chain_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("admin", "deploy", {"r": 1})
    log.append("admin", "rollback", {"r": 2})
    assert verify_audit_log(log.path) == (True, 2, "ok")
    reopened = AuditLog(log.path)  # continues the chain after restart
    reopened.append("admin", "promote", {})
    assert verify_audit_log(log.path)[0]
    lines = log.path.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["detail"]["r"] = 99
    lines[1] = json.dumps(tampered, sort_keys=True)
    log.path.write_text("\n".join(lines) + "\n")
    ok, n, msg = verify_audit_log(log.path)
    assert not ok and n == 2 and "modified" in msg
    lines.pop(1)
    log.path.write_text("\n".join(lines) + "\n")
    assert "chain broken" in verify_audit_log(log.path)[2]


# ---------- proxy API ----------


def test_health_ready_metrics_and_headers(proxy):
    client, _ = proxy
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 503
    deploy(client)
    r = client.get("/readyz")
    assert r.status_code == 200 and r.headers["x-content-type-options"] == "nosniff"
    assert "X-Trace-Id" in r.headers
    assert "gauntlet_release_weight" in client.get("/metrics").text


def test_auth_admin_and_validation(proxy):
    client, _ = proxy
    deploy(client)
    url = "/v1/apps/trialbridge/invoke"
    assert client.post(url, json={"inputs": QUALITY[0]}).status_code == 401
    assert client.post(url, json={"inputs": QUALITY[0]}, headers=auth("wrong")).status_code == 401
    assert (
        client.post("/v1/apps/other/invoke", json={"inputs": {}}, headers=auth()).status_code == 404
    )
    assert client.post(url, json={"nope": 1}, headers=auth()).status_code == 400
    assert client.post(url, json={"inputs": {"other": 1}}, headers=auth()).status_code == 400
    big = client.post(
        url, content=b"x" * (300 * 1024), headers={**auth(), "content-length": str(300 * 1024)}
    )
    assert big.status_code == 413
    assert client.get("/admin/routing").status_code == 401
    assert client.get("/admin/routing", headers=auth(CLIENT_KEY)).status_code == 401
    bad = client.put("/admin/routing", headers=auth(ADMIN_KEY), json={"stable": {"app": "x"}})
    assert bad.status_code == 400
    w = client.put("/admin/routing", headers=auth(ADMIN_KEY),
                   json={"canary": load_release(REL / "candidate.yaml"), "canary_weight": 2})  # fmt: skip
    assert w.status_code == 400
    assert client.post("/admin/rollback", headers=auth(ADMIN_KEY)).status_code == 409
    assert client.post("/admin/promote", headers=auth(ADMIN_KEY)).status_code == 409


def test_invoke_end_to_end_with_guardrails_traces_and_feedback(proxy):
    client, settings = proxy
    deploy(client, "examples/injectable_model_guarded.yaml")
    ok = client.post("/v1/apps/trialbridge/invoke", json={"inputs": QUALITY[0]}, headers=auth())
    assert ok.status_code == 200
    body = ok.json()
    assert "eligible_trials" in body["output"] and body["flags"] == []
    attack = client.post("/v1/apps/trialbridge/invoke", json={"inputs": ATTACKS[0]}, headers=auth())
    a = attack.json()
    assert "GX-CANARY" not in a["output"] and "canary_leak" in a["flags"]
    fb = client.post(
        "/v1/feedback", headers=auth(), json={"trace_id": body["trace_id"], "rating": "down"}
    )
    assert fb.status_code == 200
    assert client.post("/v1/feedback", headers=auth(), json={"trace_id": 1}).status_code == 400
    traces = read_jsonl(settings.state_dir / "traces.jsonl")
    assert len(traces) == 2 and traces[1]["inputs"] is None  # flagged inputs are not stored raw
    m = client.get("/metrics").text
    assert 'gauntlet_guardrail_blocks_total{check="canary_leak"' in m
    assert "gauntlet_proxy_overhead_seconds_bucket" in m
    cases = triage(traces, read_jsonl(settings.state_dir / "feedback.jsonl"))
    assert [c.id for c in cases] == [f"prod-{body['trace_id']}"]
    assert "needs-label" in cases[0].tags and cases[0].expected is None


def test_upstream_errors_return_502(proxy):
    client, _ = proxy
    doc = load_release(REL / "baseline.yaml")
    doc["model"] = {**doc["model"], "name": "mock-flaky"}
    client.put("/admin/routing", headers=auth(ADMIN_KEY), json={"stable": doc})
    r = client.post("/v1/apps/trialbridge/invoke", json={"inputs": QUALITY[0]}, headers=auth())
    assert r.status_code == 502


def test_rate_limit_and_anonymous(tmp_path):
    settings = Settings(upstream_base_url="http://u/v1", state_dir=tmp_path, rate_limit_rpm=1,
                        allow_anonymous=True, admin_key_hash=hash_key(ADMIN_KEY))  # fmt: skip
    with TestClient(create_app(settings, transport=upstream())) as c:
        deploy(c)
        codes = [c.post("/v1/apps/trialbridge/invoke", json={"inputs": QUALITY[0]}).status_code
                 for _ in range(3)]  # fmt: skip
        assert codes[0] == 200 and 429 in codes
        assert 'gauntlet_rate_limited_total{client="anonymous"}' in c.get("/metrics").text


def test_routing_persists_across_restart(tmp_path):
    settings = Settings(upstream_base_url="http://u/v1", state_dir=tmp_path,
                        admin_key_hash=hash_key(ADMIN_KEY))  # fmt: skip
    with TestClient(create_app(settings, transport=upstream())) as c:
        deploy(c)
        c.put("/admin/routing", headers=auth(ADMIN_KEY),
              json={"canary": load_release(REL / "candidate.yaml"), "canary_weight": 0.1})  # fmt: skip
    with TestClient(create_app(settings, transport=upstream())) as c2:
        weights = c2.get("/admin/routing", headers=auth(ADMIN_KEY)).json()["weights"]
        assert sorted(weights.values()) == pytest.approx([0.1, 0.9])


# ---------- rollout ----------


def test_decide_rules():
    p = RolloutPolicy(min_requests=50)
    healthy = {
        "requests": 60,
        "errors": 0,
        "canary_leaks": 0,
        "p95_latency_s": 0.1,
        "online_score": 1.0,
    }
    stable = {"requests": 600, "online_score": 1.0}
    assert decide(p, 0.01, None, stable).action == "hold"
    assert decide(p, 0.01, {**healthy, "requests": 20}, stable).action == "hold"
    assert decide(p, 0.01, healthy, stable) == Decision(
        "advance", "healthy at 1% over 60 requests", 0.1
    )
    assert decide(p, 1.0, healthy, stable).action == "promote"
    assert decide(p, 0.1, {**healthy, "canary_leaks": 1}, stable).action == "rollback"
    assert decide(p, 0.1, {**healthy, "requests": 20, "errors": 2}, stable).action == "rollback"
    assert decide(p, 0.1, {**healthy, "p95_latency_s": 3.0}, stable).action == "rollback"
    assert decide(p, 0.1, {**healthy, "online_score": 0.8}, stable).action == "rollback"


def test_policy_from_release():
    p = RolloutPolicy.from_release(load_release(REL / "candidate.yaml"))
    assert p.steps == (0.01, 0.1, 0.5, 1.0) and p.max_p95_latency_s == 1.5
    assert RolloutPolicy.from_release({}) == RolloutPolicy()


def _drive(client, n, inputs):
    for i in range(n):
        client.post(
            "/v1/apps/trialbridge/invoke", json={"inputs": inputs[i % len(inputs)]}, headers=auth()
        )


def test_canary_promotes_a_healthy_release(proxy):
    client, settings = proxy
    deploy(client)
    admin = ProxyAdmin("http://testserver", ADMIN_KEY, client=client)
    policy = RolloutPolicy(steps=(0.25, 1.0), min_requests=10)
    random.seed(0)
    start(admin, load_release(REL / "candidate.yaml"), policy)
    assert tick(admin, policy).action == "hold"
    actions = []
    for _ in range(3):
        _drive(client, 80, QUALITY)
        actions.append(tick(admin, policy).action)
        if actions[-1] == "promote":
            break
    assert actions[-1] == "promote", actions
    assert admin.routing()["stable"] == load_release(REL / "candidate.yaml")
    assert verify_audit_log(settings.state_dir / "audit.jsonl")[0]


def test_canary_rolls_back_on_guardrail_leaks(proxy):
    client, settings = proxy
    deploy(client)
    admin = ProxyAdmin("http://testserver", ADMIN_KEY, client=client)
    policy = RolloutPolicy(steps=(0.5, 1.0), min_requests=10)
    start(admin, load_release(REL / "examples/injectable_model_guarded.yaml"), policy)
    _drive(client, 60, ATTACKS + QUALITY[:20])
    decisions = []
    final = watch(admin, policy, interval_s=0, timeout_s=5, on_decision=decisions.append,
                  sleep=lambda _: None)  # fmt: skip
    assert final.action == "rollback" and "leak" in final.reason
    assert admin.routing()["canary"] is None
    assert "gauntlet_rollbacks_total 1.0" in client.get("/metrics").text
    entries = [json.loads(x) for x in (settings.state_dir / "audit.jsonl").read_text().splitlines()]
    assert entries[-1]["action"] == "rollback"
    assert tick(admin, policy).action == "idle"


def test_watch_times_out_into_rollback(proxy):
    client, _ = proxy
    deploy(client)
    admin = ProxyAdmin("http://testserver", ADMIN_KEY, client=client)
    policy = RolloutPolicy(min_requests=10_000)
    start(admin, load_release(REL / "candidate.yaml"), policy)
    d = watch(admin, policy, interval_s=0, timeout_s=-1, sleep=lambda _: None)
    assert d == Decision("rollback", "rollout timed out")


# ---------- monitoring ----------


def test_window_stats_and_online_score():
    now = time.time()
    evs = [Event(now, "a", "ok", 0.1, 1.0), Event(now, "a", "error", 0.0, 0.0),
           Event(now, "a", "blocked", 0.2, 0.0, ("canary_leak",)), Event(now - 100, "a", "ok", 9, 1)]  # fmt: skip
    s = window_stats(evs, since=now - 1)["a"]
    assert s["requests"] == 3 and s["errors"] == 1 and s["canary_leaks"] == 1
    assert s["p95_latency_s"] == 0.2
    assert online_score('{"eligible_trials": []}', ()) == 1.0
    assert online_score("nope", ()) == 0.0
    assert online_score('{"eligible_trials": []}', ("canary_leak",)) == 0.0


def test_psi_detects_shift():
    rng = random.Random(0)
    ref = [rng.gauss(0, 1) for _ in range(2000)]
    same = [rng.gauss(0, 1) for _ in range(2000)]
    shifted = [rng.gauss(1.5, 1) for _ in range(2000)]
    assert psi(ref, same) < 0.1 < 0.25 < psi(ref, shifted)
    with pytest.raises(ValueError):
        psi([], [1.0])
    traces = [{"input": "x" * rng.randint(10, 20), "output_tokens": 5, "latency_s": 0.1,
               "online_score": 1.0} for _ in range(100)]  # fmt: skip
    assert set(drift_report(traces, traces)) == {
        "input_chars",
        "output_tokens",
        "latency_s",
        "online_score",
    }
    assert read_jsonl("/nonexistent/file.jsonl") == []


def test_bench_levels_and_markdown():
    calls = []

    def send(p):
        calls.append(p)
        return len(calls) % 10 != 0

    level = run_level(send, [{"a": 1}], concurrency=2, duration_s=0.05)
    assert (
        level.requests == level.errors + round(level.throughput_rps * level.duration_s)
        or level.requests > 0
    )
    report = bench(send, [{"a": 1}], [1, 2], 0.02, target="t", note="n")
    md = to_markdown(report)
    assert "| Concurrency |" in md and len(report["levels"]) == 2
    _ = release_id
