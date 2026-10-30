"""Statistics used by the release gate.

Everything here is pure Python and dependency-free, so the gate's maths can be
audited and unit-tested against known values. See ADR-0001 and ADR-0002.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass

__all__ = [
    "GateDecision",
    "cohens_kappa",
    "fail_class_precision_recall",
    "non_inferiority_gate",
    "paired_bootstrap_ci",
    "weighted_kappa",
    "wilson_interval",
]


@dataclass(frozen=True)
class GateDecision:
    """Outcome of a paired non-inferiority test (candidate vs baseline)."""

    passed: bool
    superior: bool
    mean_diff: float
    ci_low: float
    ci_high: float
    margin: float
    n_cases: int

    def summary(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        extra = " (superior)" if self.superior else ""
        return (
            f"{verdict}{extra}: mean diff {self.mean_diff:+.4f}, "
            f"95% CI [{self.ci_low:+.4f}, {self.ci_high:+.4f}], "
            f"margin -{self.margin:.4f}, n={self.n_cases}"
        )


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile of an already sorted sequence, q in [0, 1]."""
    if not sorted_values:
        raise ValueError("empty sequence")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0, 1]")
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def paired_bootstrap_ci(
    candidate: Sequence[float],
    baseline: Sequence[float],
    *,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Percentile bootstrap CI for mean(candidate - baseline) on paired cases.

    Returns (mean_diff, ci_low, ci_high). Resamples case indices with
    replacement so the pairing between candidate and baseline is preserved.
    """
    if len(candidate) != len(baseline):
        raise ValueError("candidate and baseline must score the same cases")
    n = len(candidate)
    if n < 2:
        raise ValueError("need at least 2 paired cases")
    if not 0.5 < confidence < 1.0:
        raise ValueError("confidence must be in (0.5, 1)")
    if n_resamples < 100:
        raise ValueError("n_resamples too small to be meaningful")

    diffs = [c - b for c, b in zip(candidate, baseline, strict=True)]
    mean_diff = sum(diffs) / n
    # Statistical resampling, not security: B311 does not apply.
    rng = random.Random(seed)  # nosec B311
    means = []
    for _ in range(n_resamples):
        total = 0.0
        for _ in range(n):
            total += diffs[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    alpha = 1.0 - confidence
    return mean_diff, _percentile(means, alpha / 2), _percentile(means, 1 - alpha / 2)


def non_inferiority_gate(
    candidate: Sequence[float],
    baseline: Sequence[float],
    *,
    margin: float = 0.02,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int = 0,
) -> GateDecision:
    """Pass if the CI lower bound of (candidate - baseline) exceeds -margin.

    Superiority is reported only when the lower bound is above zero.
    """
    if margin < 0:
        raise ValueError("margin must be non-negative")
    mean_diff, lo, hi = paired_bootstrap_ci(
        candidate, baseline, confidence=confidence, n_resamples=n_resamples, seed=seed
    )
    return GateDecision(
        passed=lo > -margin,
        superior=lo > 0,
        mean_diff=mean_diff,
        ci_low=lo,
        ci_high=hi,
        margin=margin,
        n_cases=len(candidate),
    )


def cohens_kappa(rater_a: Sequence[Hashable], rater_b: Sequence[Hashable]) -> float:
    """Cohen's kappa for two raters on nominal labels.

    Returns 1.0 when both raters always use the same single label (agreement is
    perfect and chance agreement is also 1, which is otherwise undefined).
    """
    if len(rater_a) != len(rater_b):
        raise ValueError("raters must label the same items")
    n = len(rater_a)
    if n == 0:
        raise ValueError("no items")
    observed = sum(1 for a, b in zip(rater_a, rater_b, strict=True) if a == b) / n
    count_a = Counter(rater_a)
    count_b = Counter(rater_b)
    expected = sum(count_a[k] * count_b.get(k, 0) for k in count_a) / (n * n)
    if math.isclose(expected, 1.0):
        return 1.0
    return (observed - expected) / (1 - expected)


def weighted_kappa(
    rater_a: Sequence[int],
    rater_b: Sequence[int],
    *,
    categories: Sequence[int],
    weights: str = "quadratic",
) -> float:
    """Weighted kappa for ordinal labels (e.g. 1-5 rubric scores).

    weights: "linear" or "quadratic" disagreement weights.
    """
    if len(rater_a) != len(rater_b):
        raise ValueError("raters must label the same items")
    if not rater_a:
        raise ValueError("no items")
    cats = list(categories)
    k = len(cats)
    if k < 2:
        raise ValueError("need at least 2 categories")
    index = {c: i for i, c in enumerate(cats)}
    for v in (*rater_a, *rater_b):
        if v not in index:
            raise ValueError(f"label {v!r} not in categories")
    if weights not in ("linear", "quadratic"):
        raise ValueError("weights must be 'linear' or 'quadratic'")

    def w(i: int, j: int) -> float:
        d = abs(i - j) / (k - 1)
        return d if weights == "linear" else d * d

    n = len(rater_a)
    observed = [[0.0] * k for _ in range(k)]
    for a, b in zip(rater_a, rater_b, strict=True):
        observed[index[a]][index[b]] += 1
    row = [sum(r) for r in observed]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    num = sum(w(i, j) * observed[i][j] for i in range(k) for j in range(k))
    den = sum(w(i, j) * row[i] * col[j] / n for i in range(k) for j in range(k))
    if math.isclose(den, 0.0):
        return 1.0
    return 1 - num / den


def wilson_interval(successes: int, trials: int, *, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (e.g. attack success rate)."""
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not 0 <= successes <= trials:
        raise ValueError("successes must be within [0, trials]")
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def fail_class_precision_recall(
    judge: Sequence[Hashable], human: Sequence[Hashable], *, fail_label: Hashable = "fail"
) -> tuple[float, float]:
    """Precision and recall of the judge on the human-labelled 'fail' class.

    Missing a real failure (low recall) is the costly error for a gate, so it is
    reported separately from kappa. Returns NaN where the ratio is undefined.
    """
    if len(judge) != len(human):
        raise ValueError("judge and human must label the same items")
    tp = sum(1 for j, h in zip(judge, human, strict=True) if j == fail_label and h == fail_label)
    fp = sum(1 for j, h in zip(judge, human, strict=True) if j == fail_label and h != fail_label)
    fn = sum(1 for j, h in zip(judge, human, strict=True) if j != fail_label and h == fail_label)
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    return precision, recall
