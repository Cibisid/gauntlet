# Gauntlet — Design Document

**Status:** Draft v0.1 · **Author:** Cibi · **Last updated:** 2026-10-30

Gauntlet is an eval-gated release platform for LLM and agent systems. No prompt, model, tool or routing change reaches users unless it passes offline evaluations, security test packs and latency/cost budgets. It then rolls out through a canary that rolls itself back when online quality or SLOs regress.

It extends my existing **LLM Gateway & Agent Platform** (the data plane). It uses **TrialBridge** (clinical-trial matching) as the first system under test, and adds one **self-hosted vLLM backend** so cost, latency and quality can be compared against API models.

---

## 1. Problem

Teams ship LLM features by editing prompts, swapping models and adding tools. Each change can silently reduce answer quality, open a prompt-injection path or double the cost. Unit tests do not catch these failures. The real gaps are:

- **No regression signal.** Prompt and model changes are reviewed by eye on a handful of examples.
- **Untrusted judges.** Teams use LLM-as-judge scores without measuring whether the judge agrees with humans.
- **Security is a one-off.** Prompt-injection and data-exfiltration tests run once, not on every change.
- **Rollouts are all-or-nothing.** A bad change reaches 100% of traffic before anyone notices.
- **Cost and latency are invisible** until the bill or the complaints arrive.

The 2026 job postings I analysed (1,402 career-board descriptions and 63 hand-read ones; see `docs/market-evidence.md`) ask for exactly these capabilities: evaluation and quality gates, guardrails, observability, cost and latency control, and CI/CD for model and prompt changes.

## 2. Goals and non-goals

**Goals**
1. Version every behaviour-changing artifact (prompt, model, parameters, tool set, routing policy) as an immutable **Release**.
2. Run a **gate** on each candidate Release: quality (non-inferiority against the current production Release), security packs, and latency/cost budgets. A failing gate blocks the merge.
3. Only allow an **LLM judge** to gate once its agreement with human labels is measured and above a threshold.
4. **Canary rollout** with automatic rollback on online-quality or SLO breach.
5. Turn **production failures into regression cases** through a triage-and-label loop.
6. Measure **cost per request and per 1K users**, and compare API models against a self-hosted vLLM backend.

**Non-goals (explicitly out of scope)**
- Training or pre-training models. Fine-tuning appears only in an optional stretch milestone.
- Multi-region, multi-tenant SaaS. This is a single-tenant platform with tenancy boundaries designed but not built.
- Writing custom GPU kernels or modifying vLLM internals.
- Building a general observability product. Standard tools (OpenTelemetry, Prometheus, Grafana) are used.

## 3. Users and use cases

| Actor | Main use |
|---|---|
| Feature engineer | Opens a PR changing a prompt or model and gets a gate report on the PR |
| Reviewer / on-call | Watches canary health and approves or rolls back |
| Labeler (me, then volunteers) | Labels sampled outputs to calibrate judges |
| End user | Uses TrialBridge through the gateway |

## 4. Service level objectives

These are targets. Each is measured and published in `benchmarks/`, and the README reports actual results, including misses.

| SLO | Target |
|---|---|
| Gateway added latency (excluding model time) | p95 < 40 ms at 50 RPS |
| Guardrail added latency | p95 < 60 ms |
| Gate run, 300-case suite, API models | < 15 min end to end |
| Rollback after a sustained breach | < 2 min from detection |
| Gateway availability during demo windows | 99.5% |
| Judge eligibility to gate | Cohen's κ ≥ 0.60 against ≥ 200 human labels per rubric |

## 5. Architecture

```
            ┌───────────── Control plane (Gauntlet) ─────────────┐
 PR / CLI ──▶ Release registry ─▶ Gate runner ─▶ Gate report (PR)  │
            │      │                  │  ▲                         │
            │      │            Eval store (Postgres + S3)         │
            │      ▼                  │  │                         │
            │ Rollout controller ◀── Online scorer ◀── Trace sampler│
            └──────┼──────────────────────────────────────▲────────┘
                   │ release weights                       │ OTel traces
 Client ──▶ LLM Gateway (data plane: auth, rate limit, guardrails, routing)
                   ├──▶ API providers (Claude, OpenAI, …)
                   └──▶ vLLM on GPU node (open-weight model)
            Prometheus / Grafana / Alertmanager  ◀── metrics from all services
```

### 5.1 Components

- **LLM Gateway (existing, extended).** OpenAI-compatible API. New pieces:
  - Resolves each request to a Release using weighted routing (canary percentages).
  - Runs input and output guardrails.
  - Emits OpenTelemetry spans with GenAI semantic attributes: model, tokens, latency, release ID and guardrail verdicts.
- **Release registry.** Immutable, content-addressed Release documents (YAML in git, mirrored to Postgres). A Release is `{prompt templates, model ref, params, tools, routing policy, guardrail policy}`.
- **Gate runner.** Runs the candidate and the baseline Release on the same case set and applies the statistics in §6. Posts a markdown report to the PR and sets a required check.
- **Judge service.** Rubric-based LLM judges with versioned rubrics. Each rubric version stores its measured κ and only gates once it qualifies.
- **Security packs.** Eval suites mapped to the OWASP Top 10 for LLM Applications (2026) and the OWASP Top 10 for Agentic Applications:
  - direct and indirect prompt injection, including injection through tool output and retrieved documents
  - sensitive-data disclosure
  - excessive agency (a write tool called when only a read was warranted)
  - unbounded consumption
- **Rollout controller.** Moves canary weight 1% → 10% → 50% → 100%. At each step it checks online scores and SLOs over a minimum sample, and rolls back automatically on breach.
- **Online scorer and drift monitor.**
  - Samples production traces and scores them with qualified judges.
  - Tracks drift in the input embedding distribution (population stability index on clustered embeddings) and in score distributions.
- **Triage queue and labeling UI.** Flagged traces (user thumbs-down, guardrail trips, low judge scores) become candidate regression cases after human labeling.
- **vLLM backend.** One open-weight model on one GPU, used for cost and latency comparison and as a router target.

### 5.2 Key flows

1. **PR gate.** A developer edits `releases/trialbridge/candidate.yaml`. CI calls the gate runner, which evaluates the candidate and the baseline on the pinned case set (quality suite plus security packs) and checks budgets. Pass or fail is posted on the PR, and the check is required for merge.
2. **Rollout.** Merging to main deploys the candidate at 1% weight. The controller advances on healthy windows and rolls back on breach. Every transition is audit-logged.
3. **Failure → test.** A flagged trace goes to triage, gets a human label, and is added to the case set with provenance. The next gate includes it.

## 6. Evaluation methodology (the hard part)

- **Paired comparison.** Candidate and baseline run on identical cases. The metric is the per-case score difference.
- **Non-inferiority gate.** Compute a 95% bootstrap confidence interval for the mean difference (candidate − baseline). The gate passes if the lower bound is greater than −δ, where δ is the declared tolerance (default 0.02 on a 0–1 scale). This answers "is it at least not worse?" rather than chasing statistically meaningless "improvements".
- **Superiority claim.** Only claimed when the lower bound is greater than 0.
- **Judge calibration.** Cohen's κ (weighted κ for ordinal rubrics) between judge and human labels. Each rubric also reports precision and recall on the "fail" class, because missing failures is the costly error.
- **Variance control.**
  - Fixed seeds and temperature 0 for judges.
  - k repeated samples for stochastic candidates, with a reported consistency rate (the share of cases whose verdict is identical across k runs).
- **Hard gates.** Security packs are pass/fail per case with zero tolerance on critical cases. Case counts are reported with a Wilson interval on the attack success rate.
- **Data hygiene.** The case set is split into *dev* (used while iterating prompts) and *holdout* (used only by the gate) to avoid overfitting prompts to the gate.

## 7. Security

The full STRIDE threat model is in `docs/threat-model.md`. Headline controls:

- **Authentication and authorization.**
  - API keys hashed with argon2, scoped per client.
  - Admin actions (release promotion, rollback) require OIDC SSO plus role-based access control.
  - Least-privilege IAM per service, managed with Terraform.
  - No long-lived cloud keys in CI; GitHub OIDC is used instead.
- **Untrusted model input.**
  - All tool output and retrieved text is treated as untrusted model input.
  - Tool calls are checked against an allow-list policy per Release.
  - Write-capable tools need explicit policy approval.
- **Data handling.**
  - PII redaction in traces before storage.
  - Prompts and outputs encrypted at rest.
  - Retention limits on stored traces.
- **Rate limiting and budgets.** Rate limits per key and token budgets per tenant cover unbounded consumption.
- **Audit log.** Append-only log of release, gate, rollout and admin events.
- **Supply chain.**
  - SAST (Semgrep, Bandit), dependency scanning (pip-audit, OSV), container scanning (Trivy), SBOM (Syft, CycloneDX).
  - DAST (OWASP ZAP baseline) against staging.
  - All of it runs in CI, with findings tracked in `docs/security-report.md`.

## 8. Cost model

Every request records input and output tokens and model price, giving cost per request. Self-hosted cost is GPU-hour price ÷ measured throughput at the SLO.

Published numbers will cover:

- cost per request for each Release
- cost per 1K active users under a stated usage assumption
- a monthly infrastructure bill for the demo deployment

Guard rails on spend:

- a hard budget alarm (AWS Budgets)
- GPU nodes that only run for benchmark windows
- scale-to-zero for non-demo periods

## 9. Testing strategy

| Layer | What |
|---|---|
| Unit | Statistics (bootstrap, κ, Wilson), policy evaluation, routing math |
| Integration | Gateway ↔ fake provider, gate runner ↔ Postgres (testcontainers) |
| Contract | OpenAI-compatible API schema tests; provider adapters against recorded fixtures |
| End to end | PR → gate → merge → canary → injected regression → automatic rollback, run on a kind cluster in CI |
| Load | k6 against the gateway with a mock model (overhead SLO) and against vLLM (throughput and latency curves) |
| Eval regression | The gate itself runs on every PR that touches releases or prompts |

## 10. Deployment

- **Local.** `make up` runs everything on kind/k3d with a mock model, so a reviewer can reproduce it without cloud spend.
- **Cloud (AWS, Terraform).**
  - VPC and EKS (or k3s on a single EC2 instance; see ADR-0003)
  - RDS Postgres, S3, ECR
  - Secrets Manager
  - GPU node pool for vLLM, spot instances, benchmark windows only
- **CI/CD (GitHub Actions).**
  - Pipeline: lint → unit → integration → security scans → build and sign image → gate (if releases changed) → deploy to staging → end-to-end → manual approval → production.

## 11. Milestones

See `docs/plan.md`. The summary, about 14 weeks:

| Weeks | Milestone |
|---|---|
| 1–2 | Eval core (statistics, case schema, runner), CI, local stack |
| 3–4 | Judges plus labeling, κ measured on ≥ 200 labels for 2 rubrics |
| 5–6 | Gate in PRs with the TrialBridge suite; first real gate reports |
| 7–8 | Guardrails plus OWASP security packs; attack-rate benchmarks |
| 9–10 | Canary rollout controller, auto-rollback, observability, alerts |
| 11–12 | vLLM backend, cost/latency benchmarks, cost-aware routing |
| 13–14 | Terraform on AWS, DAST, security report, write-up and demo video |

## 12. Risks

| Risk | Mitigation |
|---|---|
| Human labeling is slow | Start labeling in week 3; small, sharp rubrics; recruit 2 classmates for inter-annotator κ |
| Judge κ stays low | Narrow the rubric, add reference answers, or fall back to programmatic checks for that criterion |
| GPU cost overrun | Benchmarks scheduled in windows; spot instances; budget alarm |
| Scope creep | Non-goals are enforced; any new feature needs an ADR |
| Gate overfitting | Dev/holdout split; holdout refreshed from production failures |

## 13. Open questions
- EKS versus k3s on EC2 for the demo cluster: cost against realism (ADR-0003, proposed).
- Which open-weight model for vLLM, given TrialBridge task quality and a single L4 or A10G GPU.
