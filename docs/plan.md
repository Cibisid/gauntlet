# 14-Week Plan

Each milestone ends with something demonstrable and a short entry in `CHANGELOG.md`. Numbers go in the README only after they are measured.

| Week | Deliverable | Done when |
|---|---|---|
| 1 | Repo, CI (lint, unit, Semgrep, pip-audit), eval statistics core | CI green; bootstrap and κ tested against known values |
| 2 | Case schema, runner, local stack on kind with a mock model; ADR-0003 decided | `make up` works on a clean machine |
| 3 | TrialBridge case set v1 (dev and holdout), labeling UI, first 100 labels | Cases versioned; labels exported |
| 4 | Judges for 2 rubrics; κ on ≥ 200 labels; second labeler on a 20% overlap | Qualification records stored; κ reported honestly |
| 5 | Gate runner plus PR comment and required check | A real prompt PR gets a pass/fail report |
| 6 | Release registry (content-addressed); gateway routes by Release | Gateway trace shows the Release ID |
| 7 | Guardrails (input/output, PII redaction); OWASP LLM pack v1 | Attack success rate measured with an interval |
| 8 | Agentic pack (indirect injection, exfiltration, excessive agency); tool allow-list | Pack runs in the gate |
| 9 | OpenTelemetry tracing, Prometheus metrics, Grafana dashboards, alerts | Dashboards for latency, cost, guardrails, scores |
| 10 | Canary controller plus auto-rollback; end-to-end injected-regression test | End-to-end test proves rollback within the SLO |
| 11 | vLLM backend on a GPU node; k6 latency/throughput curves | Benchmarks published with hardware, model and config |
| 12 | Cost-aware routing; cost per request and per 1K users | Cost table in the README |
| 13 | Terraform (AWS), ZAP DAST, Trivy, SBOM, security report | All findings resolved or justified |
| 14 | Write-up, architecture diagram, 5-minute demo video, polish | Ready to present in a system-design interview |

**Weekly guard rail:** if a week slips, cut scope from the "stretch" list, never from tests or the security report.

**Stretch (only if ahead):**
- distill a small model for one TrialBridge sub-task
- SPRT sequential gating
- a merged upstream PR to vLLM or an eval library
