# Security Report

Tracks every finding from SAST, DAST, dependency/container scans and the threat model (`docs/threat-model.md`). Each finding is either **resolved** (with the fixing commit) or **accepted** (with a written justification). Nothing stays "open" at release.

| ID | Source | Finding | Severity | Status | Resolution / justification |
|---|---|---|---|---|---|
| F-001 | Bandit B311 | `random.Random` in `stats.paired_bootstrap_ci` | Low | Accepted | Used for statistical resampling with a fixed seed for reproducibility, not for any security purpose. Suppressed inline with `# nosec B311` and this note. |

| F-002 | Ruff S311 | `random.Random` in `scripts/make_synthetic_cases.py` | Low | Accepted | Seeded generation of synthetic test data, so it must be deterministic. Not shipped in the package; ignored for `scripts/**` in ruff config. |

**Controls landed in week 2:**
- **Prompt rendering (T3).** Templates use `string.Template`, so braces in patient data cannot inject format directives (tested).
- **Release validation.** Secret-like keys in a release are rejected; `*_ref` references are allowed (tested).
- **Provider client.** The API key comes from the environment and never appears in errors (tested).
- **Mock server.** Optional bearer auth, a 1 MB body limit, and 400/404 on bad input (tested).
- **Containers.** Non-root user, read-only root filesystem, all capabilities dropped, `no-new-privileges`, Trivy scan in CI.
- **Security pack v0.** 40 critical indirect prompt-injection and system-prompt-leakage cases (OWASP LLM01/LLM07), run by every gate.

## Threat model status (v1.0, 2026-11-02)

| ID | Threat | Control in place | Verified by | Status |
|---|---|---|---|---|
| T1 | Stolen/guessed API key | scrypt-hashed keys, per-key rate limits, 401 on bad keys | unit + DAST | Mitigated |
| T2 | Unauthorised promotion | Separate admin key for routing/promote/rollback; audit log | unit + kind e2e | Mitigated (OIDC/RBAC: future) |
| T3 | Indirect injection via data | Output protected-string filter; input detector flag-only | security pack; held-out eval (ADR-0008) | Partially mitigated |
| T4 | Poisoned dependency/image | pip-audit, Trivy, SBOM, Semgrep, Bandit, gitleaks in CI | CI | Mitigated (image signing: future) |
| T5 | Case-set tampering | Case sets in git, content hash per run, byte-for-byte regeneration check | CI | Mitigated |
| T6 | Repudiation | Hash-chained audit log, `gauntlet audit-verify` | unit (tamper test) | Mitigated |
| T7 | PII in traces | Output PII redaction; inputs redacted before trace storage; flagged inputs not stored raw | unit | Mitigated (regex-level) |
| T8 | Exfiltration via tools | No tool calls in v1 | n/a | Deferred (agentic tools not in scope) |
| T9 | System prompt extraction | Protected-string filter blocks verbatim leaks | security pack, canary e2e | Partially (paraphrased leaks not caught) |
| T10 | Unbounded consumption | Rate limits, 256 KB body limit, max_input_chars, max_tokens per release | unit | Mitigated |
| T11 | GPU saturation | Resource limits in manifests; rollback on p95 breach | rollout unit tests | Partially (no admission queue) |
| T12 | Over-permissioned agent | No tools in v1 | n/a | Deferred |
| T13 | Over-broad IAM | Least-privilege IAM, GitHub OIDC (no static keys), IMDSv2 | checkov (0 failed, 20 justified skips) | Mitigated in code; not yet applied |

**Scan results at v1.0:**
- **Bandit:** 0 open findings (F-001 accepted).
- **Semgrep:** 0 findings.
- **pip-audit:** 0 known vulnerabilities.
- **checkov:**
  - Kubernetes: 261 passed, 0 failed, 9 justified skips
  - Terraform: 187 passed, 0 failed, 20 justified skips
  - Dockerfile: 65 passed, 0 failed
- **ZAP baseline and Trivy:** run in CI on every push.

