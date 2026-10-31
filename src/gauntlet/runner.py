"""Run a release over a case set and record per-case results."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from gauntlet.cases import Case
from gauntlet.prompts import render_messages
from gauntlet.providers import Provider, ProviderError
from gauntlet.release import release_id
from gauntlet.scorers import get_scorer


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

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CaseResult:
        return cls(**{k: raw[k] for k in cls.__dataclass_fields__})


def request_cost(model: Mapping[str, Any], input_tokens: int, output_tokens: int) -> float:
    """Cost in USD from per-million-token prices declared on the release's model."""
    price_in = float(model.get("price_in_per_mtok", 0.0))
    price_out = float(model.get("price_out_per_mtok", 0.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def _run_one(release: Mapping[str, Any], rid: str, case: Case, provider: Provider) -> CaseResult:
    model = release["model"]
    scorer = get_scorer(case.scorer)
    try:
        messages = render_messages(release["prompt"], case.inputs)
        completion = provider.complete(model["name"], messages, release.get("params", {}))
    except ProviderError as exc:
        return CaseResult(
            case.id,
            case.suite,
            case.split,
            case.critical,
            rid,
            0.0,
            0.0,
            0,
            0,
            0.0,
            str(exc),
            "",
        )
    return CaseResult(
        case_id=case.id,
        suite=case.suite,
        split=case.split,
        critical=case.critical,
        release_id=rid,
        score=scorer(completion.text, case.expected),
        latency_ms=round(completion.latency_ms, 3),
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
        cost_usd=request_cost(model, completion.input_tokens, completion.output_tokens),
        error=None,
        output=completion.text,
    )


def run_release(
    release: Mapping[str, Any],
    cases: Sequence[Case],
    provider: Provider,
    *,
    concurrency: int = 8,
) -> list[CaseResult]:
    """Run every case through the release. Results keep the input order.

    Provider failures are recorded per case (score 0, ``error`` set) rather than
    aborting the run; the gate decides whether the error rate is acceptable.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    rid = release_id(release)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(lambda c: _run_one(release, rid, c, provider), cases))


def write_results(path: str | Path, results: Iterable[CaseResult]) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(asdict(r), sort_keys=True) + "\n")


def read_results(path: str | Path) -> list[CaseResult]:
    with Path(path).open(encoding="utf-8") as fh:
        return [CaseResult.from_dict(json.loads(line)) for line in fh if line.strip()]
