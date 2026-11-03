"""Per-release summary of a run: the numbers that go in docs/results.md.

Everything here is computed from result files; nothing is estimated.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from gauntlet.gate import percentile
from gauntlet.runner import CaseResult
from gauntlet.stats import wilson_interval


def summarize(results: Sequence[CaseResult], *, split: str = "holdout") -> dict[str, Any]:
    ok = [r for r in results if not r.error]
    quality = [r for r in ok if r.suite == "quality" and r.split == split]
    security = [r for r in ok if r.suite == "security"]
    lat = [r.latency_ms for r in ok]
    leaks = sum(1 for r in security if "canary_leak" in r.flags)
    flagged = sum(1 for r in security if "prompt_injection" in r.flags)
    exact = sum(1 for r in quality if r.score >= 1.0)
    out: dict[str, Any] = {
        "release_id": results[0].release_id if results else "",
        "cases": len(results),
        "errors": len(results) - len(ok),
        "error_rate": (len(results) - len(ok)) / len(results) if results else math.nan,
        "quality_n": len(quality),
        "quality_mean_f1": _mean([r.score for r in quality]),
        "quality_exact": exact,
        "quality_exact_ci95": wilson_interval(exact, len(quality)) if quality else None,
        "security_n": len(security),
        "raw_leak_attempts": leaks,
        "raw_leak_ci95": wilson_interval(leaks, len(security)) if security else None,
        "served_leaks": sum(1 for r in security if r.score < 1.0),
        "detector_flagged": flagged,
        "latency_p50_ms": percentile(lat, 50),
        "latency_p95_ms": percentile(lat, 95),
        "mean_input_tokens": _mean([float(r.input_tokens) for r in ok]),
        "mean_output_tokens": _mean([float(r.output_tokens) for r in ok]),
        "mean_cost_usd": _mean([r.cost_usd for r in ok]),
    }
    return out


def to_markdown(rows: Mapping[str, Mapping[str, Any]]) -> str:
    """One column per labelled run (e.g. model name)."""
    names = list(rows)
    lines = [
        "| metric | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    spec: list[tuple[str, Any]] = [
        ("release", lambda s: f"`{s['release_id']}`"),
        ("cases run (errors)", lambda s: f"{s['cases']} ({s['errors']})"),
        ("holdout mean F1", lambda s: _f(s["quality_mean_f1"], 3)),
        ("holdout exact match", _exact),
        ("injection cases where the model leaked the canary", _leaks),
        ("leaks served to users (after output guardrail)", lambda s: str(s["served_leaks"])),
        ("injections flagged by input detector", lambda s: str(s["detector_flagged"])),
        (
            "latency p50 / p95 (ms)",
            lambda s: f"{_f(s['latency_p50_ms'], 0)} / {_f(s['latency_p95_ms'], 0)}",
        ),
        (
            "mean tokens in / out",
            lambda s: f"{_f(s['mean_input_tokens'], 0)} / {_f(s['mean_output_tokens'], 0)}",
        ),
        ("mean cost per case (USD, list price)", lambda s: _f(s["mean_cost_usd"], 6)),
    ]
    for label, fn in spec:
        lines.append(f"| {label} | " + " | ".join(fn(rows[n]) for n in names) + " |")
    return "\n".join(lines) + "\n"


def _exact(s: Mapping[str, Any]) -> str:
    n = s["quality_n"]
    if not n:
        return "n/a"
    lo, hi = s["quality_exact_ci95"]
    return f"{s['quality_exact']}/{n} ({s['quality_exact'] / n:.1%}, CI {lo:.1%}-{hi:.1%})"


def _leaks(s: Mapping[str, Any]) -> str:
    n = s["security_n"]
    if not n:
        return "n/a"
    lo, hi = s["raw_leak_ci95"]
    return f"{s['raw_leak_attempts']}/{n} (CI {lo:.1%}-{hi:.1%})"


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else math.nan


def _f(value: float, digits: int) -> str:
    return "n/a" if value is None or math.isnan(value) else f"{value:.{digits}f}"
