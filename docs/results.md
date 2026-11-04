# Measured results

Everything below was measured on 2026-11-02 and can be reproduced with the commands shown. Each result notes its data source, so mock or synthetic numbers are never mistaken for real-model quality.

## 1. Release gate verdicts (`make demo-all`)
These run on the synthetic TrialBridge-style suite (474 holdout quality cases and 40 critical injection cases) against the deterministic mock model. They show the gate's *behaviour*, not model quality.

| Candidate | Verdict | Deciding check |
|---|---|---|
| Reworded prompt | PASS | Quality diff +0.0003, 95% CI [−0.021, +0.020], within −0.03 margin |
| Cheaper model (ignores exclusions) | FAIL | Quality diff −0.074, 95% CI [−0.095, −0.055] |
| Injectable model, no output guardrail | FAIL | 40/40 attacks leaked the system prompt |
| Same model behind the output guardrail | PASS | 0/40 leaks reached the output |

## 2. Gate sizing finding (ADR-0006)
With 192 holdout cases, the 95% CI on a harmless rewording was [−0.037, +0.026]. That was too wide to show non-inferiority at δ = 0.03, so the gate rejected the change. The fix was to grow the case set to 474 holdout cases, which narrowed the CI to about ±0.02, rather than loosening δ.

## 3. Prompt-injection detector (ADR-0008)
| Test set | Recall | False positives |
|---|---|---|
| Synthetic templates (known when patterns were written) | 40/40, 100% (CI 91–100%) | 0/800 (CI 0–0.5%) |
| **Held-out phrasings written after freezing patterns** | **0/20, 0% (CI 0–16%)** | 0/10 (CI 0–28%) |

Conclusion: pattern matching does not generalise, so enforcement moved to the output side. Reproduce the first row with `gauntlet guardrail-eval --cases cases/trialbridge/synthetic_v1.jsonl`. The held-out row comes from `cases/security/heldout_*.txt`.

## 4. Proxy performance (`benchmarks/proxy_mock_upstream.md`)
- In-handler overhead, excluding upstream time, over 6,720 requests: 99.7% took ≤ 1 ms and 100% took ≤ 5 ms. The SLO is p95 < 40 ms.
- Throughput against a 30 ms mock upstream on a shared 2-vCPU box:

| Concurrency | Throughput | p50 | p95 |
|---|---|---|---|
| 1 | 27 req/s | 36 ms | 39 ms |
| 8 | 160 req/s | 50 ms | 60 ms |
| 32 | 250 req/s | 96 ms | 146 ms |

At concurrency 32 the box saturates (5 of 3,904 requests failed).

## 5. Canary rollout (tests and `scripts/k8s_e2e.sh` on kind)
- A candidate whose leaks are blocked by the guardrail is **rolled back automatically** on the first evaluation window containing a blocked leak. The audit log records the rollback, and its hash chain verifies.
- A healthy candidate advances 50% → 100% and is **promoted**.

## 6. Real models: can we swap gpt-oss-120b for gpt-oss-20b?
Run [41755631589](https://github.com/Cibisid/gauntlet/actions/runs/41755631589) of the `real-model-gate` workflow, measured on 2026-11-03. The models were served by Groq's free tier, and the run was completed across four resumed runs because of the daily token quota.
The two releases are identical except for the model, and `reasoning_effort` is `low`. The cases are the 514 gate cases: 474 held-out quality cases and 40 injection cases. The patients and trials are **synthetic**.

| Metric | gpt-oss-120b (baseline) | gpt-oss-20b (candidate) |
|---|---|---|
| Errors | 0 / 514 | 0 / 514 |
| Holdout exact match | 472/474 (99.6%, CI 98.5–99.9%) | 453/474 (95.6%, CI 93.3–97.1%) |
| Holdout mean F1 | 0.996 | 0.971 |
| Injection cases where the model leaked the canary | 0/40 | 0/40 |
| Latency p50 / p95 | 635 / 920 ms | 462 / 934 ms |
| Mean tokens in / out | 519 / 165 | 519 / 137 |
| Mean cost per case (list price) | $0.000177 | $0.000080 |

**Gate verdict: FAIL on quality non-inferiority.**
- The mean paired difference is −0.0247, with a 95% CI of [−0.0390, −0.0120] against a margin of −0.03.
- Security, error-rate, latency and cost checks all pass.

**Why it fails even though the drop is under 3 points.** The observed drop (2.5 points) is inside the margin.
But the confidence interval reaches −3.9 points, so the data cannot rule out a drop larger than we accept.
A naive "compare the averages" check would have shipped this change, while the paired test blocks it.
The cheaper model would save about 55% per case, so this is a real trade-off for a product owner to decide on the evidence, not something the pipeline should wave through.

**Caveats.**
- Neither real model obeyed the 40 injection templates, so this run did not exercise the output guardrail on real leaks. The mock-model demo is still the only evidence of the guardrail blocking leaks (section 1).
- The input detector flagged all 40 cases because they come from its known templates. Held-out recall is 0/20 (section 3).
- Costs are computed from list prices entered at run time ($0.15/$0.60 and $0.075/$0.30 per 1M tokens). Check them against Groq's pricing page.

## Not measured yet (needs resources outside this repo)
- **Real-model results on real (non-synthetic) clinical data.** Section 6 uses real models on synthetic cases.
- **vLLM throughput and latency on a GPU.** Needs `enable_gpu = true` in `infra/terraform` (about $1/hour while on).
- **Judge agreement with humans.** Needs at least 200 human labels: `gauntlet label` then `gauntlet qualify`. Tests use *simulated* labels only.
- **AWS deployment.** The Terraform passes checkov; it needs your AWS account to apply.
