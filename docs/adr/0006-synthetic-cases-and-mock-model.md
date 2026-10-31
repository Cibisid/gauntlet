# ADR-0006: A synthetic case set and a deterministic mock model for CI

**Status:** Accepted · **Date:** 2026-10-31

## Context
The gate has to be tested end to end on every push: run releases, score them, compare them and reach the right verdict. Calling real models in CI costs money, needs secrets, and is nondeterministic, which makes the tests flaky. Real TrialBridge cases need human labels, and those don't exist yet (week 3).

## Decision
- `gauntlet.trialsim` defines a rule-checkable version of the eligibility task: age range, required condition and exclusions. Its ground truth is computable.
- `scripts/make_synthetic_cases.py` deterministically generates 800 quality cases (dev/holdout split) and 40 critical prompt-injection cases. The file is committed, and CI checks it regenerates byte-for-byte.
- `gauntlet.mock_server` is an OpenAI-compatible server whose models simulate specific behaviours:
  - `mock-accurate`: correct, with about 3% deterministic noise
  - `mock-sloppy`: ignores exclusions
  - `mock-obedient`: follows injected instructions
  - `mock-flaky`: returns intermittent 503s
- Integration tests assert the gate's verdict for each example release.

## Consequences
- Every gate path (pass, quality fail, security fail, provider errors, budgets) is exercised on every push at zero cost.
- Mock and synthetic numbers are never reported as model benchmarks. The README labels them as pipeline demonstrations.
- The first real finding came from this setup. With 192 holdout cases, the 95% interval was too wide to prove a harmless prompt rewording non-inferior at δ = 0.03, so the gate rejected it. The suite was grown to 800 cases (474 in holdout) rather than loosening δ. Real suites will need sizing the same way: roughly n ≥ (2·z·σ/δ)² paired cases.
- Real TrialBridge cases are added as a separate suite from week 3. The synthetic suite stays as a fast CI regression check.
