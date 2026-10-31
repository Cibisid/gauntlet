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

Threat-model items T1–T13 are tracked here as their controls land (weeks 7–13).
