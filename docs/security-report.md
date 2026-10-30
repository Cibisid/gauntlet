# Security Report

Tracks every finding from SAST, DAST, dependency/container scans and the threat model (`docs/threat-model.md`). Each finding is either **resolved** (with the fixing commit) or **accepted** (with a written justification). Nothing stays "open" at release.

| ID | Source | Finding | Severity | Status | Resolution / justification |
|---|---|---|---|---|---|
| F-001 | Bandit B311 | `random.Random` in `stats.paired_bootstrap_ci` | Low | Accepted | Used for statistical resampling with a fixed seed for reproducibility, not for any security purpose. Suppressed inline with `# nosec B311` and this note. |

Threat-model items T1–T13 are tracked here as their controls land (weeks 7–13).
