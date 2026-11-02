# Changelog

## 1.0.0 — 2026-11-02
- **LLM judges.** Versioned rubrics; qualification against human labels (κ, fail precision/recall, n); refuse to gate with an unqualified or changed judge (ADR-0002).
- **Labelling.** Interactive `gauntlet label` with stratified sampling and resume support; `gauntlet agreement` for inter-annotator κ.
- **Guardrails.** Protected-string output blocking, PII redaction (email, phone, SSN, Luhn-checked cards) and the input injection detector. The full guardrail policy is applied in the runner, so the gate tests the guarded system.
- **Honest guardrail finding.** The detector caught 0/20 held-out attacks, so enforcement moved to the output side (ADR-0008).
- **Proxy.** FastAPI data plane: stable/canary routing, scrypt keys, rate limits, body limits, security headers, Prometheus metrics, sampled PII-redacted traces, feedback, hash-chained audit log, admin API (ADR-0007).
- **Rollout controller.** Advance/hold/promote/rollback on error rate, p95, guardrail leaks and online score; `gauntlet rollout` commands.
- **Monitoring.** PSI drift, triage of flagged traces into candidate cases, Grafana dashboard, 7 Prometheus alerts and runbooks.
- **Benchmarking.** `gauntlet bench`; proxy overhead ≤ 1 ms for 99.7% of requests (benchmarks/).
- **Deploy.** Hardened Kubernetes manifests (restricted PSS, NetworkPolicies), vLLM GPU manifest, Terraform for AWS (k3s on EC2, optional GPU spot, ECR, S3, Secrets Manager, GitHub OIDC, budgets).
- **CI.** kind-cluster canary end-to-end, OWASP ZAP baseline, terraform fmt/validate, checkov; manual `real-model-gate` workflow.


## 0.2.0 — 2026-10-31 (week 2)
- Case schema with quality/security suites and dev/holdout splits; tamper-evident case-set hash.
- Prompt rendering with `string.Template`, so user data cannot inject format directives.
- Scorers: JSON set F1 (eligibility), canary-leak detection (security), exact match.
- OpenAI-compatible provider with retries on 408/429/5xx and backoff; the key is never logged.
- Runner: concurrent, per-case latency, tokens and cost; failures recorded rather than fatal.
- Gate: paired non-inferiority, zero critical security failures with a Wilson CI, error-rate cap, p95 latency and cost budgets; markdown report; `gauntlet` CLI.
- Deterministic mock model server (accurate / sloppy / obedient / flaky) and a synthetic TrialBridge-style case set (800 quality and 40 injection cases); ADR-0006.
- Example releases with asserted verdicts; integration tests through real HTTP and the CLI.
- Dockerfile (multi-stage, non-root), docker-compose stack, CI release-gate job, image build, compose smoke test, Trivy scan.
- Finding: 192 holdout cases were too few to show non-inferiority at δ = 0.03, so the suite grew to 474 holdout cases.

## 0.1.0 — 2026-10-30 (week 1)
- Design doc, ADRs 0001–0005, STRIDE threat model, 14-week plan, market evidence.
- Eval statistics core: paired bootstrap non-inferiority gate, Cohen's and weighted kappa, Wilson interval, judge fail-class precision/recall.
- Content-addressed Release IDs with inline-secret rejection.
- CI: ruff, mypy (strict), pytest with a 90% coverage gate, Bandit, Semgrep, pip-audit, gitleaks, CycloneDX SBOM.
