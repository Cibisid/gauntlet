# Gauntlet

**Eval-gated releases for LLM and agent systems.** No prompt, model, tool or routing change reaches users unless it:

- proves it is not worse than what's live (paired non-inferiority on a held-out case set)
- passes OWASP-mapped security packs (prompt injection, data exfiltration, excessive agency)
- stays inside latency and cost budgets

It then ships through a canary that rolls itself back when online quality or SLOs regress.

> **Status: week 1 of 14.** What exists today is the evaluation statistics core, release identity, CI and the design. Everything else below is planned, and no numbers are claimed until they are measured. See [`docs/plan.md`](docs/plan.md).

## Why
Most LLM features ship on vibes: someone tweaks a prompt, eyeballs five outputs and merges. Gauntlet treats prompts and models like code. Every change is versioned, tested, gated, rolled out gradually and observable. The design follows what 2026 job descriptions actually ask for; see [`docs/market-evidence.md`](docs/market-evidence.md).

## How it fits together
- **Data plane:** my existing [LLM Gateway](https://github.com/Cibisid/llm-gateway) (OpenAI-compatible, multi-provider, MCP tools). It is extended with release-weighted routing, guardrails and OpenTelemetry tracing.
- **Control plane:** Gauntlet. It holds the release registry, gate runner, qualified LLM judges, security packs and the canary controller.
- **System under test:** [TrialBridge](https://github.com/Cibisid/trialbridge) (clinical-trial matching).
- **Self-hosted model:** one open-weight model on vLLM, used to compare cost and latency against API models.

Full architecture, SLOs and trade-offs are in [`docs/design.md`](docs/design.md). Decisions are recorded in [`docs/adr/`](docs/adr/), and the security posture is in [`docs/threat-model.md`](docs/threat-model.md) and [`docs/security-report.md`](docs/security-report.md).

## What works now
```python
from gauntlet.stats import non_inferiority_gate, cohens_kappa

decision = non_inferiority_gate(candidate_scores, baseline_scores, margin=0.02)
print(decision.summary())
# illustrative output format:
# PASS: mean diff -0.0040, 95% CI [-0.0151, +0.0071], margin -0.0200, n=300

cohens_kappa(judge_labels, human_labels)  # a judge must reach >= 0.60 before it may gate
```

## Develop
```bash
make install   # editable install with dev tools
make check     # ruff, mypy --strict, pytest (90% coverage gate), bandit, pip-audit
```

## Results
_None yet. Benchmarks, judge agreement, attack success rates and cost per request will be published here with methodology, hardware and raw data as each milestone lands._
