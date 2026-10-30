import math
import random

import pytest

from gauntlet.stats import (
    cohens_kappa,
    fail_class_precision_recall,
    non_inferiority_gate,
    paired_bootstrap_ci,
    weighted_kappa,
    wilson_interval,
)

# ---------- Cohen's kappa ----------


def test_cohens_kappa_textbook_example():
    # 50 items: yes/yes 20, yes/no 5, no/yes 10, no/no 15  -> kappa = 0.4
    a = ["y"] * 20 + ["y"] * 5 + ["n"] * 10 + ["n"] * 15
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert cohens_kappa(a, b) == pytest.approx(0.4)


def test_cohens_kappa_perfect_and_single_label():
    assert cohens_kappa(["a", "b", "a"], ["a", "b", "a"]) == pytest.approx(1.0)
    assert cohens_kappa(["x"] * 5, ["x"] * 5) == 1.0


def test_cohens_kappa_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        cohens_kappa(["a"], ["a", "b"])


# ---------- weighted kappa ----------


def test_weighted_kappa_perfect_agreement():
    s = [1, 2, 3, 4, 5, 3]
    assert weighted_kappa(s, s, categories=[1, 2, 3, 4, 5]) == pytest.approx(1.0)


def test_weighted_kappa_penalises_far_disagreement_more():
    human = [1, 2, 3, 4, 5] * 4
    near = [min(5, h + 1) for h in human]
    far = [6 - h for h in human]  # fully reversed scale
    cats = [1, 2, 3, 4, 5]
    k_near = weighted_kappa(human, near, categories=cats)
    k_far = weighted_kappa(human, far, categories=cats)
    assert k_near > k_far
    assert k_far < 0


def test_weighted_kappa_matches_reference_value():
    # Hand-computed quadratic-weighted kappa for a small 3-category table.
    a = [0, 0, 1, 1, 2, 2]
    b = [0, 1, 1, 2, 2, 2]
    # Quadratic weights: w(0,1)=w(1,2)=0.25, w(0,2)=1.
    # Observed weighted disagreement = 0.25 + 0.25 = 0.5.
    # Rows (2,2,2), cols (1,2,3): expected = (7 + 2 + 3) / 6 = 2.0 -> kappa = 0.75.
    assert weighted_kappa(a, b, categories=[0, 1, 2]) == pytest.approx(0.75)


def test_weighted_kappa_rejects_unknown_label():
    with pytest.raises(ValueError):
        weighted_kappa([1, 9], [1, 2], categories=[1, 2, 3])


# ---------- Wilson interval ----------


@pytest.mark.parametrize(
    ("k", "n", "lo", "hi"),
    [(0, 10, 0.0, 0.2775), (5, 10, 0.2366, 0.7634), (10, 10, 0.7225, 1.0)],
)
def test_wilson_interval_known_values(k, n, lo, hi):
    got_lo, got_hi = wilson_interval(k, n)
    assert got_lo == pytest.approx(lo, abs=1e-4)
    assert got_hi == pytest.approx(hi, abs=1e-4)


def test_wilson_interval_validates_input():
    with pytest.raises(ValueError):
        wilson_interval(3, 2)
    with pytest.raises(ValueError):
        wilson_interval(0, 0)


# ---------- bootstrap & gate ----------


def test_identical_scores_pass_but_are_not_superior():
    scores = [0.2, 0.9, 0.5, 0.7, 1.0, 0.0]
    d = non_inferiority_gate(scores, scores, margin=0.02)
    assert d.passed and not d.superior
    assert d.mean_diff == 0 and d.ci_low == 0 and d.ci_high == 0


def test_clear_regression_fails():
    rng = random.Random(1)
    base = [rng.random() for _ in range(300)]
    cand = [max(0.0, b - 0.10) for b in base]
    d = non_inferiority_gate(cand, base, margin=0.02, n_resamples=2000)
    assert not d.passed
    assert d.ci_high < 0


def test_clear_improvement_is_superior():
    rng = random.Random(2)
    base = [rng.random() * 0.8 for _ in range(300)]
    cand = [min(1.0, b + 0.10) for b in base]
    d = non_inferiority_gate(cand, base, n_resamples=2000)
    assert d.passed and d.superior


def test_small_noisy_suite_is_not_overconfident():
    # Tiny suite with a real but small regression: the interval should be wide
    # enough that the gate refuses to pass it.
    base = [1, 0, 1, 1, 0, 1, 1, 0, 1, 1]
    cand = [1, 0, 0, 1, 0, 1, 0, 0, 1, 1]
    d = non_inferiority_gate(cand, base, margin=0.02, n_resamples=2000)
    assert not d.passed
    assert d.ci_low < -0.1


def test_bootstrap_is_deterministic_for_a_seed():
    rng = random.Random(3)
    base = [rng.random() for _ in range(50)]
    cand = [rng.random() for _ in range(50)]
    assert paired_bootstrap_ci(cand, base, seed=7, n_resamples=500) == paired_bootstrap_ci(
        cand, base, seed=7, n_resamples=500
    )


def test_bootstrap_rejects_unpaired_input():
    with pytest.raises(ValueError):
        paired_bootstrap_ci([0.1, 0.2], [0.1])


def test_gate_summary_is_readable():
    d = non_inferiority_gate([0.5, 0.6, 0.7], [0.5, 0.6, 0.7], n_resamples=200)
    assert d.summary().startswith("PASS")


# ---------- judge fail-class metrics ----------


def test_fail_class_precision_recall():
    human = ["fail", "fail", "pass", "pass", "fail"]
    judge = ["fail", "pass", "fail", "pass", "fail"]
    p, r = fail_class_precision_recall(judge, human)
    assert p == pytest.approx(2 / 3)
    assert r == pytest.approx(2 / 3)


def test_fail_class_metrics_undefined_is_nan():
    p, r = fail_class_precision_recall(["pass"], ["pass"])
    assert math.isnan(p) and math.isnan(r)


# ---------- input validation ----------


@pytest.mark.parametrize(
    "kwargs",
    [{"confidence": 0.4}, {"confidence": 1.0}, {"n_resamples": 10}],
)
def test_bootstrap_rejects_bad_parameters(kwargs):
    with pytest.raises(ValueError):
        paired_bootstrap_ci([0.1, 0.2, 0.3], [0.1, 0.2, 0.3], **kwargs)


def test_bootstrap_needs_two_cases():
    with pytest.raises(ValueError):
        paired_bootstrap_ci([0.1], [0.1])


def test_gate_rejects_negative_margin():
    with pytest.raises(ValueError):
        non_inferiority_gate([0.1, 0.2], [0.1, 0.2], margin=-0.1)


def test_weighted_kappa_validation():
    with pytest.raises(ValueError):
        weighted_kappa([1], [1, 2], categories=[1, 2])
    with pytest.raises(ValueError):
        weighted_kappa([], [], categories=[1, 2])
    with pytest.raises(ValueError):
        weighted_kappa([1], [1], categories=[1])
    with pytest.raises(ValueError):
        weighted_kappa([1], [1], categories=[1, 2], weights="cubic")


def test_weighted_kappa_linear_weights_and_degenerate_case():
    assert weighted_kappa([1, 2, 3], [1, 2, 3], categories=[1, 2, 3], weights="linear") == 1.0
    assert weighted_kappa([2, 2], [2, 2], categories=[1, 2, 3]) == 1.0


def test_cohens_kappa_rejects_empty():
    with pytest.raises(ValueError):
        cohens_kappa([], [])


def test_fail_class_metrics_reject_mismatch():
    with pytest.raises(ValueError):
        fail_class_precision_recall(["fail"], [])
