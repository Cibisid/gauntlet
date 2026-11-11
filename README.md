# Gauntlet

[![ci](https://github.com/Cibisid/gauntlet/actions/workflows/ci.yml/badge.svg)](https://github.com/Cibisid/gauntlet/actions/workflows/ci.yml)

**[Try the live demo](https://cibisid.github.io/#demo-gauntlet)** · **[Read the case study](https://cibisid.github.io/projects/gauntlet.html)** · Built by [Cibi Siddarth](https://cibisid.github.io)

> **In one sentence:** a safety check that stops a bad AI update before customers see it, and undoes a release on its own if problems show up with real traffic.

**Eval-gated releases for LLM and agent systems.** Gauntlet treats prompts, models and guardrails like code. Every change is versioned and tested offline against a held-out case set, security packs and budgets. It then ships through a canary that rolls itself back when live traffic shows a problem.

```
 PR changes a release ──► offline gate ──► canary 1% ─► 10% ─► 50% ─► 100%
                          │ quality: paired non-inferiority      │ live checks: errors, p95,
                          │ security: zero critical leaks        │ guardrail leaks, online score
                          │ errors, p95 latency, cost budgets    └─► auto-rollback + audit log
```

## What's in it
| Area | What it does |
|---|---|
| **Offline gate** | Paired bootstrap non-inferiority, OWASP-mapped injection pack, error-rate cap, latency and cost budgets; PR report |
| **LLM judges** | Versioned rubrics; a judge may gate only after it agrees with human labels (κ ≥ 0.6, fail recall ≥ 0.8, n ≥ 200) |
| **Labelling** | `gauntlet label` interactive tool, stratified sampling, inter-annotator κ |
| **Guardrails** | Output-side protected-string blocking and PII redaction; input injection detector as a monitored signal ([ADR-0008](docs/adr/0008-guardrail-strategy.md)) |
| **Proxy** | FastAPI data plane: weighted stable/canary routing, scrypt-hashed keys, rate limits, Prometheus metrics, PII-redacted traces, hash-chained audit log, admin API |
| **Rollout** | Canary controller: advance, hold, promote, or automatic rollback |
| **Monitoring** | Grafana dashboard, 7 Prometheus alerts with runbooks, PSI drift, failure → test-case triage |
| **Deploy** | Hardened Docker image, Compose stack, Kubernetes manifests (restricted PSS, NetworkPolicies), vLLM GPU manifest, Terraform for AWS |
| **CI** | Lint, strict types, 137 tests at about 98% coverage, release gate, kind-cluster canary end-to-end, OWASP ZAP DAST, Bandit, Semgrep, gitleaks, pip-audit, SBOM, Trivy, checkov, terraform validate |

## Results (measured; details in [docs/results.md](docs/results.md))
- **Gate verdicts on the demo releases:**
  - harmless rewording → PASS (Δ +0.0003, CI ±0.02)
  - cheaper model → FAIL (Δ −0.074)
  - injectable model without output guardrail → FAIL (40/40 leaks)
  - the same model with the guardrail → PASS (0/40)
- **Proxy overhead:** ≤ 1 ms for 99.7% of 6,720 requests (SLO p95 < 40 ms). Peak throughput was 250 req/s on a shared 2-vCPU box against a 30 ms mock upstream.
- **Real models (Groq, gpt-oss-120b → gpt-oss-20b, 514 gate cases each):**
  - exact match 99.6% vs 95.6%
  - the smaller model is about 55% cheaper per case
  - gate **FAIL**: the observed drop is 2.5 points, but its 95% CI reaches 3.9 points, beyond the 3-point margin
  - neither model leaked under injection
  - details in [results §6](docs/results.md#6-real-models-can-we-swap-gpt-oss-120b-for-gpt-oss-20b)
- **Honest negative result:** the pattern-based injection detector caught 40/40 known templates but **0/20 held-out attacks**. Enforcement therefore moved to the output side.
- **Gate sizing:** 192 holdout cases were too few to show a harmless change was non-inferior at δ = 0.03. The suite grew to 474 rather than the margin being loosened.

> The gate and canary demos use a deterministic **mock model** and a **synthetic** TrialBridge-style task so CI is free and repeatable. They prove the system's behaviour, not any model's quality. Real-model results come from the `real-model-gate` workflow ([guide](docs/real-models.md)). See [Not done yet](#not-done-yet).

## Quickstart (no API keys)
```bash
pip install -e ".[dev]"
make demo-all                                   # offline gate on 4 example releases
docker compose up --build                       # mock model + proxy + a gate run
docker compose --profile observability up       # + Prometheus :9090, Grafana :3000
```

Canary against the local proxy:
```bash
export GAUNTLET_ADMIN_KEY=<long random string>
export GAUNTLET_ADMIN_KEY_HASH=$(GAUNTLET_KEY_TO_HASH=$GAUNTLET_ADMIN_KEY gauntlet hash-key)
docker compose up -d mock-llm gauntlet-proxy
gauntlet rollout deploy --proxy http://localhost:8080 --release releases/trialbridge/baseline.yaml
gauntlet rollout start  --proxy http://localhost:8080 --release releases/trialbridge/candidate.yaml
gauntlet rollout watch  --proxy http://localhost:8080 --release releases/trialbridge/candidate.yaml
```

## How a change ships
1. Edit `releases/trialbridge/candidate.yaml` (prompt, model, params, guardrails, budgets or rollout).
2. Open a PR. The **release-gate** job runs baseline and candidate on the same cases and posts the report. Any failing check blocks the merge.
3. After merging, run `gauntlet rollout start` then `watch`. The controller widens traffic only while error rate, p95 latency, guardrail leaks and online score stay healthy. Otherwise it rolls back and writes the reason to the audit log.

## Using real models
`--base-url` takes any OpenAI-compatible endpoint: the [LLM Gateway](https://github.com/Cibisid/llm-gateway), vLLM (`deploy/k8s/gpu/vllm.yaml`), or a hosted API. Keys come from `GAUNTLET_API_KEY` and are never logged.

## Not done yet
- **Judge qualification.** Needs at least 200 human labels via `gauntlet label`. No record is committed, because simulated labels don't count.
- **Real TrialBridge cases.** Format and instructions are in `cases/trialbridge/real/README.md`.
- **AWS apply.** `infra/terraform` is written and scanned but has not been applied (needs an AWS account; about $38/month baseline).
- **High availability.** The proxy runs as a single replica; shared routing state is the next step ([ADR-0007](docs/adr/0007-in-repo-proxy-and-routing-state.md)).

## Docs
- [Design](docs/design.md)
- ADRs:
  - [0001 non-inferiority](docs/adr/0001-non-inferiority-gate.md)
  - [0002 judge qualification](docs/adr/0002-judge-qualification.md)
  - [0006 synthetic suite](docs/adr/0006-synthetic-cases-and-mock-model.md)
  - [0007 proxy](docs/adr/0007-in-repo-proxy-and-routing-state.md)
  - [0008 guardrails](docs/adr/0008-guardrail-strategy.md)
- [Threat model](docs/threat-model.md)
- [Security report](docs/security-report.md)
- [Results](docs/results.md)
- [Runbooks](deploy/observability/runbooks.md)
- [Terraform](infra/terraform/README.md)

## CLI
```
offline:     id · run · gate · label · qualify · agreement · guardrail-eval
production:  proxy · hash-key · rollout {deploy,start,tick,watch,promote,rollback,status}
             audit-verify · drift · triage · bench
testing:     mock-server
```
