# ADR-0002: LLM judges must qualify against human labels before they can gate

**Status:** Accepted · **Date:** 2026-10-30

## Context
LLM-as-judge is cheap and scalable, but an uncalibrated judge can wave regressions through. Job postings in 2026 increasingly ask engineers to measure evaluator quality against human labels (for example, FICO Applied AI, 2026).

## Decision
Every rubric version stores a qualification record covering:
- Cohen's κ (weighted κ for ordinal scales) between judge and human labels on at least 200 labeled cases
- precision and recall for the "fail" class
- the judge model, prompt hash and temperature

A rubric may gate only if κ ≥ 0.60 and fail-recall ≥ 0.80. Any change to the judge model or rubric prompt creates a new version that must re-qualify. Two human labelers overlap on 20% of cases to report human–human κ as the ceiling.

## Consequences
- Real labeling effort, planned from week 3.
- Judges that cannot reach the bar must be narrowed or replaced with programmatic checks.
- The README can honestly state how trustworthy each gate is.

## Alternatives considered
- **Trust the judge.** Unmeasurable risk.
- **Human review of every gate.** Does not scale and defeats CI.
