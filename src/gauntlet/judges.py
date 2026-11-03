"""LLM-as-judge scoring with mandatory qualification (ADR-0002).

A rubric is a versioned YAML file. A judge may only score gating cases once a
qualification record shows it agrees with human labels:
Cohen's kappa >= 0.60 and fail-class recall >= 0.80 on >= 200 labelled items.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from gauntlet.providers import Provider
from gauntlet.scorers import extract_json_object
from gauntlet.stats import cohens_kappa, fail_class_precision_recall

MIN_KAPPA = 0.60
MIN_FAIL_RECALL = 0.80
MIN_LABELS = 200


class JudgeError(RuntimeError):
    """Raised when a judge cannot be used."""


@dataclass(frozen=True)
class Rubric:
    name: str
    version: int
    model: str
    instructions: str

    @property
    def key(self) -> str:
        return f"{self.name}@v{self.version}"

    @property
    def prompt_hash(self) -> str:
        blob = json.dumps(asdict(self), sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:16]

    @classmethod
    def load(cls, path: str | Path) -> Rubric:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(
            name=str(raw["name"]),
            version=int(raw["version"]),
            model=str(raw["model"]),
            instructions=str(raw["instructions"]),
        )


def judge_messages(
    rubric: Rubric, inputs: Mapping[str, Any], output: str, reference: Any
) -> list[dict[str, str]]:
    task = json.dumps(dict(inputs), sort_keys=True)
    ref = json.dumps(reference, sort_keys=True)
    return [
        {
            "role": "system",
            "content": rubric.instructions
            + '\nRespond with JSON only: {"verdict": "pass" | "fail", "reason": "<one sentence>"}',
        },
        {
            "role": "user",
            "content": f"TASK INPUT:\n{task}\n\nREFERENCE:\n{ref}\n\nRESPONSE TO GRADE:\n{output}",
        },
    ]


def parse_verdict(text: str) -> str | None:
    obj = extract_json_object(text)
    if obj is None:
        return None
    verdict = str(obj.get("verdict", "")).strip().lower()
    return verdict if verdict in {"pass", "fail"} else None


class Judge:
    def __init__(self, rubric: Rubric, provider: Provider) -> None:
        self.rubric = rubric
        self.provider = provider

    def verdict(self, inputs: Mapping[str, Any], output: str, reference: Any) -> str:
        completion = self.provider.complete(
            self.rubric.model,
            judge_messages(self.rubric, inputs, output, reference),
            {"temperature": 0, "max_tokens": 200},
        )
        return parse_verdict(completion.text) or "fail"  # unparseable -> conservative fail


@dataclass(frozen=True)
class Qualification:
    rubric: str
    prompt_hash: str
    n: int
    kappa: float
    fail_precision: float
    fail_recall: float
    qualified: bool
    reasons: tuple[str, ...]

    def save(self, directory: str | Path) -> Path:
        path = Path(directory) / f"{self.rubric}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> Qualification:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        raw["reasons"] = tuple(raw["reasons"])
        return cls(**raw)


def qualify(
    rubric: Rubric,
    judge_labels: Sequence[str],
    human_labels: Sequence[str],
    *,
    min_labels: int = MIN_LABELS,
) -> Qualification:
    """Compare judge verdicts with human labels on the same items."""
    if len(judge_labels) != len(human_labels):
        raise ValueError("judge and human labels must cover the same items")
    n = len(human_labels)
    kappa = cohens_kappa(judge_labels, human_labels) if n else float("nan")
    precision, recall = fail_class_precision_recall(judge_labels, human_labels)
    reasons = []
    if n < min_labels:
        reasons.append(f"only {n} labels (need {min_labels})")
    if not kappa >= MIN_KAPPA:
        reasons.append(f"kappa {kappa:.2f} < {MIN_KAPPA}")
    if not recall >= MIN_FAIL_RECALL:
        reasons.append(f"fail recall {recall:.2f} < {MIN_FAIL_RECALL}")
    return Qualification(
        rubric=rubric.key,
        prompt_hash=rubric.prompt_hash,
        n=n,
        kappa=kappa,
        fail_precision=precision,
        fail_recall=recall,
        qualified=not reasons,
        reasons=tuple(reasons),
    )


def require_qualified(rubric: Rubric, directory: str | Path) -> Qualification:
    """Return the rubric's qualification record or raise if it may not gate."""
    path = Path(directory) / f"{rubric.key}.json"
    if not path.exists():
        raise JudgeError(f"{rubric.key} has no qualification record; run `gauntlet qualify`")
    record = Qualification.load(path)
    if record.prompt_hash != rubric.prompt_hash:
        raise JudgeError(f"{rubric.key} changed since it was qualified; re-qualify it")
    if not record.qualified:
        raise JudgeError(f"{rubric.key} is not qualified: {'; '.join(record.reasons)}")
    return record


def describe(record: Qualification) -> str:
    def f(x: float) -> str:
        return "n/a" if math.isnan(x) else f"{x:.2f}"

    status = "QUALIFIED" if record.qualified else "NOT QUALIFIED"
    return (
        f"{record.rubric}: {status} — n={record.n}, kappa={f(record.kappa)}, "
        f"fail precision={f(record.fail_precision)}, fail recall={f(record.fail_recall)}"
        + (f" ({'; '.join(record.reasons)})" if record.reasons else "")
    )
