# ADR-0001: Gate releases on paired non-inferiority, not on raw average score

**Status:** Accepted · **Date:** 2026-10-30

## Context
A gate has to decide whether a candidate Release may replace the current one. Comparing average scores ("0.81 vs 0.79") is noisy: with 300 cases, swings of a few points happen by chance. Requiring a significant *improvement* blocks harmless refactors such as a cheaper model or a shorter prompt, and those are exactly the changes we want to ship.

## Decision
Run candidate and baseline on the **same cases**. Compute the per-case score difference and a **95% paired bootstrap confidence interval** of the mean difference. **Pass if the lower bound is greater than −δ** (default δ = 0.02, set per suite). Report superiority only when the lower bound is greater than 0. Security packs are separate hard gates with zero tolerance on critical cases.

## Consequences
- Cheaper or faster changes can ship when they are "not meaningfully worse", which matches real cost/quality trade-offs.
- δ is a product decision and must be declared per suite, in review.
- Small suites give wide intervals and fail more often. That is intended: it pushes the case set to grow.

## Alternatives considered
- **Mean-score threshold.** Ignores variance, so it is flaky.
- **Paired t-test.** Assumes normal differences. Judge scores are bounded and lumpy, so the bootstrap is more honest.
- **Sequential testing (SPRT).** Saves cost on large suites. Deferred until suites exceed about 1,000 cases.
