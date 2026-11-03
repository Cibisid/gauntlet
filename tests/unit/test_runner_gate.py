import math

import httpx
import pytest

from gauntlet.cases import Case
from gauntlet.gate import GateInputError, evaluate_gate, percentile
from gauntlet.providers import Completion, OpenAICompatibleProvider, ProviderError
from gauntlet.runner import CaseResult, read_results, request_cost, run_release, write_results

RELEASE = {
    "app": "t",
    "prompt": {"user_template": "$q"},
    "model": {"name": "m", "price_in_per_mtok": 1.0, "price_out_per_mtok": 2.0},
    "params": {"temperature": 0},
}


class FakeProvider:
    def __init__(self, answers, fail_on=()):
        self.answers = answers
        self.fail_on = set(fail_on)

    def complete(self, model, messages, params):
        q = messages[-1]["content"]
        if q in self.fail_on:
            raise ProviderError("boom")
        return Completion(self.answers[q], input_tokens=100, output_tokens=10, latency_ms=12.5)


def _case(i, suite="quality", split="holdout", critical=False):
    return Case(
        id=f"c{i}",
        suite=suite,
        split=split,
        inputs={"q": f"q{i}"},
        expected="yes",
        scorer="exact_match",
        critical=critical,
    )


# ---------- runner ----------


def test_run_release_scores_costs_and_records_errors(tmp_path):
    cases = [_case(1), _case(2), _case(3)]
    provider = FakeProvider({"q1": "yes", "q2": "no", "q3": "yes"}, fail_on={"q3"})
    results = run_release(RELEASE, cases, provider, concurrency=2)
    assert [r.case_id for r in results] == ["c1", "c2", "c3"]
    assert [r.score for r in results] == [1.0, 0.0, 0.0]
    assert results[0].cost_usd == pytest.approx((100 * 1.0 + 10 * 2.0) / 1e6)
    assert results[2].error and "boom" in results[2].error
    path = tmp_path / "r.jsonl"
    write_results(path, results)
    assert read_results(path) == results


def test_run_release_validates_concurrency():
    with pytest.raises(ValueError):
        run_release(RELEASE, [_case(1)], FakeProvider({"q1": "yes"}), concurrency=0)


def test_request_cost_defaults_to_zero():
    assert request_cost({}, 1000, 1000) == 0.0


# ---------- provider (no network: httpx MockTransport) ----------


def _transport(responses, seen):
    it = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = next(it)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


OK_BODY = {
    "choices": [{"message": {"content": "hi"}}],
    "usage": {"prompt_tokens": 7, "completion_tokens": 2},
}


def test_provider_retries_then_succeeds_and_sends_auth():
    seen = []
    client = httpx.Client(
        transport=_transport([(503, {}), (200, OK_BODY)], seen),
        headers={"Authorization": "Bearer k"},
    )
    p = OpenAICompatibleProvider("http://x/v1/", client=client, backoff_s=0)
    out = p.complete("m", [{"role": "user", "content": "q"}], {"temperature": 0, "ignored": 1})
    assert out.text == "hi" and out.input_tokens == 7 and out.output_tokens == 2
    assert len(seen) == 2
    assert str(seen[0].url) == "http://x/v1/chat/completions"
    assert b'"ignored"' not in seen[0].content
    p.close()


def test_provider_does_not_retry_client_errors_and_hides_key():
    seen = []
    client = httpx.Client(transport=_transport([(401, {}), (200, OK_BODY)], seen))
    p = OpenAICompatibleProvider("http://x/v1", api_key="sk-secret", client=client, backoff_s=0)
    with pytest.raises(ProviderError) as exc:
        p.complete("m", [], {})
    assert "401" in str(exc.value) and "sk-secret" not in str(exc.value)
    assert len(seen) == 1


def test_provider_gives_up_after_retries_and_rejects_malformed():
    seen = []
    client = httpx.Client(transport=_transport([(500, {})] * 3, seen))
    p = OpenAICompatibleProvider("http://x/v1", client=client, max_retries=2, backoff_s=0)
    with pytest.raises(ProviderError, match="HTTP 500"):
        p.complete("m", [], {})
    assert len(seen) == 3

    client = httpx.Client(transport=_transport([(200, {"choices": []})], []))
    p = OpenAICompatibleProvider("http://x/v1", client=client, backoff_s=0)
    with pytest.raises(ProviderError, match="malformed"):
        p.complete("m", [], {})


def test_provider_handles_transport_errors():
    def handler(request):
        raise httpx.ConnectError("down")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    p = OpenAICompatibleProvider("http://x/v1", client=client, max_retries=1, backoff_s=0)
    with pytest.raises(ProviderError, match="transport error"):
        p.complete("m", [], {})


# ---------- gate ----------


def _res(cid, score, suite="quality", split="holdout", critical=False, error=None, latency=10.0):
    return CaseResult(cid, suite, split, critical, "rel_x", score, latency, 10, 5, 0.001, error, "")


def _suite(scores, **kw):
    return [_res(f"q{i}", s, **kw) for i, s in enumerate(scores)]


SEC_OK = [_res("s1", 1.0, suite="security", critical=True)]


def test_gate_passes_equal_candidate_and_reports_stats():
    base = _suite([1.0, 0.5, 1.0, 0.0] * 10) + SEC_OK
    report = evaluate_gate(
        base, list(base), budgets={"p95_latency_ms": 50, "max_mean_cost_usd": 0.01}, n_resamples=500
    )
    assert report.passed
    md = report.to_markdown()
    assert "PASS" in md and "Mean quality score" in md
    assert report.stats["candidate_quality_mean"] == pytest.approx(0.625)


def test_gate_fails_on_regression_security_errors_and_budgets():
    base = _suite([1.0] * 50) + SEC_OK
    cand = (
        _suite([0.0] * 10 + [1.0] * 40, latency=900.0)
        + [_res("s1", 0.0, suite="security", critical=True)]
        + [_res(f"e{i}", 0.0, suite="security", error="HTTP 500") for i in range(3)]
    )
    report = evaluate_gate(
        base, cand, budgets={"p95_latency_ms": 100, "max_mean_cost_usd": 0.0001}, n_resamples=500
    )
    failed = {c.name for c in report.checks if not c.passed}
    assert failed == {
        "Quality non-inferiority",
        "Security packs (zero critical failures)",
        "Provider error rate",
        "Latency budget (p95)",
        "Cost budget (mean/request)",
    }
    assert "FAIL" in report.to_markdown()


def test_non_critical_security_failures_do_not_block():
    base = _suite([1.0] * 20) + SEC_OK
    cand = _suite([1.0] * 20) + SEC_OK + [_res("s2", 0.0, suite="security", critical=False)]
    assert evaluate_gate(base, cand, n_resamples=200).passed


def test_gate_requires_security_cases():
    base = _suite([1.0] * 5)
    report = evaluate_gate(base, base, n_resamples=200)
    assert not report.passed


def test_gate_input_errors():
    with pytest.raises(GateInputError, match="no quality"):
        evaluate_gate(SEC_OK, SEC_OK)
    with pytest.raises(GateInputError, match="different cases"):
        evaluate_gate(_suite([1.0, 1.0]), _suite([1.0]))


def test_percentile_nearest_rank():
    assert percentile([5, 1, 3, 2, 4], 95) == 5
    assert percentile([5, 1, 3, 2, 4], 50) == 3
    assert math.isnan(percentile([], 95))


def test_provider_honours_retry_after_with_cap():
    slept = []

    def handler(request):
        if len(slept) == 0 and not getattr(handler, "done", False):
            handler.done = True
            return httpx.Response(429, headers={"retry-after": "7"}, json={})
        return httpx.Response(200, json=OK_BODY)

    p = OpenAICompatibleProvider("http://x/v1", client=httpx.Client(
        transport=httpx.MockTransport(handler)), backoff_s=0.5, sleep=slept.append)  # fmt: skip
    assert p.complete("m", [], {}).text == "hi"
    assert slept == [7.0]


def test_retry_after_parsing():
    from gauntlet.providers import MAX_RETRY_AFTER_S, _retry_after_s

    assert _retry_after_s(None) is None
    assert _retry_after_s("Wed, 21 Oct 2015 07:28:00 GMT") is None
    assert _retry_after_s("9999") == MAX_RETRY_AFTER_S
    assert _retry_after_s("-3") == 0.0


def test_provider_paces_requests_to_max_rpm():
    slept = []
    client = httpx.Client(transport=_transport([(200, OK_BODY)] * 3, []))
    p = OpenAICompatibleProvider("http://x/v1", client=client, max_rpm=60, sleep=slept.append)
    for _ in range(3):
        p.complete("m", [], {})
    # first call goes at once; the next two wait for their 1-second slots
    assert len(slept) == 2 and all(0.5 < s <= 2.0 for s in slept)


def test_provider_fails_fast_on_long_retry_after_and_forwards_reasoning_params():
    seen, slept = [], []

    def handler(request):
        seen.append(request)
        return httpx.Response(429, headers={"retry-after": "3600"}, json={})

    p = OpenAICompatibleProvider("http://x/v1", client=httpx.Client(
        transport=httpx.MockTransport(handler)), sleep=slept.append)  # fmt: skip
    with pytest.raises(ProviderError, match="quota exhausted"):
        p.complete("m", [], {"reasoning_effort": "low", "include_reasoning": False})
    assert len(seen) == 1 and slept == []
    assert (
        b'"reasoning_effort": "low"' in seen[0].content
        or b'"reasoning_effort":"low"' in seen[0].content
    )
