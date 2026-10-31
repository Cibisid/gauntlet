# Gauntlet

[![ci](https://github.com/Cibisid/gauntlet/actions/workflows/ci.yml/badge.svg)](https://github.com/Cibisid/gauntlet/actions/workflows/ci.yml)

**Eval-gated releases for LLM and agent systems.** A prompt, model, tool or routing change reaches users only if it passes four checks:

- **Not worse than production.** A paired non-inferiority test on a held-out case set.
- **Survives the security packs.** Prompt injection and system-prompt leakage tests, mapped to the OWASP LLM Top 10.
- **Low provider error rate.**
- **Inside latency and cost budgets.**

From week 10 it will then ship through a canary that rolls itself back when quality or SLOs regress.

> **Status: week 2 of 14.** The gate works end to end against a deterministic mock model and a synthetic task (below). Real TrialBridge cases with human labels, LLM judges, guardrails, canary rollout, a vLLM backend and AWS deployment follow the [plan](docs/plan.md). No model benchmark numbers are claimed yet.

## Try it (about 1 minute, no API keys)

```bash
pip install -e ".[dev]"
make demo-all      # gates three example releases against the baseline
```

```
=== releases/trialbridge/examples/cheaper_model.yaml     FAIL  (quality regressed)
=== releases/trialbridge/examples/injectable_model.yaml  FAIL  (40/40 prompt injections leaked the system prompt)
=== releases/trialbridge/examples/reworded_prompt.yaml   PASS  (not meaningfully worse)
```

Each run writes a markdown report, the same one CI attaches to every pull request:

| Check | Result | Detail |
|---|---|---|
| Quality non-inferiority | **FAIL** | mean diff -0.0743, 95% CI [-0.0953, -0.0546], margin -0.0300, n=474 |
| Security packs (zero critical failures) | pass | 0/40 attacks succeeded |
| Latency budget (p95) | pass | 19 ms (limit 1500 ms) |
| Cost budget (mean/request) | pass | $0.000110 (limit $0.010000) |

*(From the cheaper-model example. The numbers come from the mock model and show the pipeline, not real model quality.)*

Docker: `make docker-up` runs the same gate in containers (non-root, read-only, all capabilities dropped).

## How the gate decides
- **Paired non-inferiority** ([ADR-0001](docs/adr/0001-non-inferiority-gate.md)). Candidate and baseline answer the same cases. The gate takes a bootstrap 95% CI of the score difference and passes if its lower bound is above -δ.
- **Sized honestly.** With 192 holdout cases the gate correctly refused to call a harmless rewording "not worse", because the interval was too wide. The fix was more cases, not a looser margin ([ADR-0006](docs/adr/0006-synthetic-cases-and-mock-model.md)).
- **Zero critical security failures**, with the attack success rate reported alongside its Wilson interval.
- **Judges must qualify** before they can gate (week 4; [ADR-0002](docs/adr/0002-judge-qualification.md)).

## Use it in a pull request
1. Edit `releases/trialbridge/candidate.yaml` (prompt, model, params or budgets).
2. Open a PR. The `release-gate` job runs the candidate and baseline and posts the report to the job summary. It fails the check if any gate fails.
3. To promote, copy the candidate to `baseline.yaml`. Every release has a content-addressed ID (`gauntlet id <file>`).

## CLI
```
gauntlet run  --release R.yaml --cases C.jsonl --base-url http://host/v1 --out results.jsonl
gauntlet gate --baseline B.jsonl --candidate C.jsonl --release R.yaml --report report.md
gauntlet id   R.yaml
gauntlet mock-server --port 8089
```
`--base-url` works with any OpenAI-compatible endpoint: the [LLM Gateway](https://github.com/Cibisid/llm-gateway), vLLM, or a hosted API. The key is read from `GAUNTLET_API_KEY`.

## Engineering
- **CI on every push:**
  - ruff and mypy `--strict`
  - unit and integration tests on Python 3.11–3.13, with a coverage gate at 90% (currently about 98%)
  - a check that the case set regenerates byte-for-byte
  - the release gate
  - Bandit and Semgrep (SAST), pip-audit, gitleaks, a CycloneDX SBOM
  - a Docker build, a compose smoke test and a Trivy image scan
- **Docs:**
  - [design doc](docs/design.md) with SLOs
  - [ADRs](docs/adr/)
  - [STRIDE threat model](docs/threat-model.md)
  - [security report](docs/security-report.md)
  - [market evidence](docs/market-evidence.md) explaining why this project exists

## Layout
```
src/gauntlet/   stats, cases, prompts, scorers, providers, runner, gate, cli, mock_server, trialsim
releases/       baseline, candidate and example releases (YAML)
cases/          versioned case sets (JSONL)
scripts/        case generator, local gate demo
tests/          unit + integration (real HTTP server, real CLI)
docs/           design, ADRs, threat model, security report, plan, research data
```
