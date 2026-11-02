"""Production monitoring helpers: drift detection and the failure -> test-case loop."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from gauntlet.cases import Case

PSI_ALERT = 0.25  # common rule of thumb: <0.1 stable, 0.1-0.25 moderate, >0.25 major shift


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def psi(reference: Sequence[float], current: Sequence[float], *, bins: int = 10) -> float:
    """Population Stability Index of ``current`` against ``reference``.

    Bin edges are reference quantiles; empty bins are smoothed with a small epsilon.
    """
    if not reference or not current:
        raise ValueError("both samples must be non-empty")
    ref = sorted(reference)
    edges = [ref[min(len(ref) - 1, int(i * len(ref) / bins))] for i in range(1, bins)]

    def hist(values: Sequence[float]) -> list[float]:
        counts = [0] * bins
        for v in values:
            idx = sum(1 for e in edges if v > e)
            counts[idx] += 1
        return [max(c / len(values), 1e-4) for c in counts]

    r, c = hist(reference), hist(current)
    return sum((ci - ri) * math.log(ci / ri) for ri, ci in zip(r, c, strict=True))


def drift_report(
    reference: Iterable[Mapping[str, Any]], current: Iterable[Mapping[str, Any]]
) -> dict[str, float]:
    """PSI on reference-free signals available for every production trace."""
    ref, cur = list(reference), list(current)
    out: dict[str, float] = {}
    signals: dict[str, Callable[[Mapping[str, Any]], float]] = {
        "input_chars": lambda t: float(len(str(t.get("input", "")))),
        "output_tokens": lambda t: float(t.get("output_tokens", 0)),
        "latency_s": lambda t: float(t.get("latency_s", 0.0)),
        "online_score": lambda t: float(t.get("online_score", 0.0)),
    }
    for name, fn in signals.items():
        out[name] = psi([fn(t) for t in ref], [fn(t) for t in cur])
    return out


def triage(
    traces: Iterable[Mapping[str, Any]],
    feedback: Iterable[Mapping[str, Any]],
) -> list[Case]:
    """Turn flagged production traces into *unlabelled* candidate regression cases.

    A trace is flagged by negative user feedback, a guardrail intervention, or a
    failed online check. Candidates carry ``expected=None`` and the tag
    ``needs-label``; ``load_cases`` accepts them, but they only join a gating
    suite after a human fills in ``expected`` (see docs/runbooks or README).
    """
    down = {f["trace_id"] for f in feedback if f.get("rating") == "down"}
    out: list[Case] = []
    seen: set[str] = set()
    for t in traces:
        reasons = []
        if t["trace_id"] in down:
            reasons.append("user-thumbs-down")
        reasons.extend(f"guardrail:{f}" for f in t.get("flags", []))
        if t.get("status") == "ok" and t.get("online_score", 1.0) < 1.0:
            reasons.append("online-check-failed")
        if not reasons or t["trace_id"] in seen or not t.get("inputs"):
            continue
        seen.add(t["trace_id"])
        out.append(
            Case(
                id=f"prod-{t['trace_id']}",
                suite="quality",
                split="dev",
                inputs=dict(t["inputs"]),
                expected=None,
                scorer="json_set_f1",
                tags=("needs-label", "from-production", *reasons),
                provenance=f"triaged from trace {t['trace_id']} (release {t.get('release_id')})",
            )
        )
    return out
