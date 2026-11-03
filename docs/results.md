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

## Not measured yet (needs resources outside this repo)
- **Real-model quality, cost and latency.** Needs an API key: run the `real-model-gate` workflow.
- **vLLM throughput and latency on a GPU.** Needs `enable_gpu = true` in `infra/terraform` (about $1/hour while on).
- **Judge agreement with humans.** Needs at least 200 human labels: `gauntlet label` then `gauntlet qualify`. Tests use *simulated* labels only.
- **AWS deployment.** The Terraform passes checkov; it needs your AWS account to apply.
