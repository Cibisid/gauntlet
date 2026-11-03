"""Run a release over a case set and record per-case results.

A release's guardrail policy (if any) is applied exactly as the proxy applies it
in production, so the gate measures the system users actually get.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from gauntlet.cases import Case
from gauntlet.guardrails import BLOCKED_OUTPUT, GuardrailPolicy, check_input, check_output
from gauntlet.judges import Judge
from gauntlet.prompts import render_messages
from gauntlet.providers import Provider, ProviderError
from gauntlet.release import release_id
from gauntlet.scorers import get_scorer

JUDGE_PREFIX = "judge:"


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    suite: str
    split: str
    critical: bool
    release_id: str
    score: float
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    error: str | None
    output: str
    flags: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CaseResult:
        values = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw}
        values["flags"] = tuple(raw.get("flags", ()))
        return cls(**values)


def request_cost(model: Mapping[str, Any], input_tokens: int, output_tokens: int) -> float:
    """Cost in USD from per-million-token prices declared on the release's model."""
    price_in = float(model.get("price_in_per_mtok", 0.0))
    price_out = float(model.get("price_out_per_mtok", 0.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def _failed(case: Case, rid: str, error: str) -> CaseResult:
    return CaseResult(
        case.id, case.suite, case.split, case.critical, rid, 0.0, 0.0, 0, 0, 0.0, error, ""
    )


def _score(case: Case, output: str, judge: Judge | None) -> float:
    if case.scorer.startswith(JUDGE_PREFIX):
        name = case.scorer[len(JUDGE_PREFIX) :]
        if judge is None or judge.rubric.name != name:
            raise ProviderError(f"case needs judge {name!r} but none is configured")
        return 1.0 if judge.verdict(case.inputs, output, case.expected) == "pass" else 0.0
    return get_scorer(case.scorer)(output, case.expected)


def _run_one(
    release: Mapping[str, Any],
    rid: str,
    case: Case,
    provider: Provider,
    policy: GuardrailPolicy | None,
    judge: Judge | None,
) -> CaseResult:
    model = release["model"]
    flags: list[str] = []
    try:
        messages = render_messages(release["prompt"], case.inputs)
        if policy is not None:
            iv = check_input(messages, policy)
            flags.extend(iv.reasons)
            if iv.blocked:
                return CaseResult(
                    case.id, case.suite, case.split, case.critical, rid,
                    _score(case, BLOCKED_OUTPUT, judge), 0.0, 0, 0, 0.0, None,
                    BLOCKED_OUTPUT, tuple(flags),
                )  # fmt: skip
        completion = provider.complete(model["name"], messages, release.get("params", {}))
        text = completion.text
        if policy is not None:
            ov = check_output(text, policy)
            flags.extend(ov.reasons)
            text = ov.text
        score = _score(case, text, judge)
    except ProviderError as exc:
        return _failed(case, rid, str(exc))
    return CaseResult(
        case_id=case.id,
        suite=case.suite,
        split=case.split,
        critical=case.critical,
        release_id=rid,
        score=score,
        latency_ms=round(completion.latency_ms, 3),
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
        cost_usd=request_cost(model, completion.input_tokens, completion.output_tokens),
        error=None,
        output=text,
        flags=tuple(flags),
    )


def run_release(
    release: Mapping[str, Any],
    cases: Sequence[Case],
    provider: Provider,
    *,
    concurrency: int = 8,
    judge: Judge | None = None,
) -> list[CaseResult]:
    """Run every case through the release. Results keep the input order.

    Provider failures are recorded per case (score 0, ``error`` set) rather than
    aborting the run; the gate decides whether the error rate is acceptable.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    rid = release_id(release)
    policy = GuardrailPolicy.from_release(release)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(lambda c: _run_one(release, rid, c, provider, policy, judge), cases))


def write_results(path: str | Path, results: Iterable[CaseResult]) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        for r in results:
            row = asdict(r)
            row["flags"] = list(r.flags)
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def read_results(path: str | Path) -> list[CaseResult]:
    with Path(path).open(encoding="utf-8") as fh:
        return [CaseResult.from_dict(json.loads(line)) for line in fh if line.strip()]
