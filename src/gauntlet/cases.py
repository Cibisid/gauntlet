"""Evaluation cases: schema, loading, validation and content hashing.

Cases live in JSONL files, one case per line. Each case belongs to a *suite*
(``quality`` or ``security``) and a *split* (``dev`` for prompt iteration,
``holdout`` for the gate only; see design §6).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUITES = frozenset({"quality", "security"})
SPLITS = frozenset({"dev", "holdout"})


class CaseError(ValueError):
    """Raised when a case file is malformed."""


@dataclass(frozen=True)
class Case:
    id: str
    suite: str
    split: str
    inputs: Mapping[str, Any]
    expected: Any
    scorer: str
    critical: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)
    provenance: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], *, where: str = "") -> Case:
        for key in ("id", "suite", "split", "inputs", "expected", "scorer"):
            if key not in raw:
                raise CaseError(f"{where}missing field {key!r}")
        if raw["suite"] not in SUITES:
            raise CaseError(f"{where}suite must be one of {sorted(SUITES)}")
        if raw["split"] not in SPLITS:
            raise CaseError(f"{where}split must be one of {sorted(SPLITS)}")
        if not isinstance(raw["inputs"], Mapping):
            raise CaseError(f"{where}inputs must be an object")
        return cls(
            id=str(raw["id"]),
            suite=raw["suite"],
            split=raw["split"],
            inputs=dict(raw["inputs"]),
            expected=raw["expected"],
            scorer=str(raw["scorer"]),
            critical=bool(raw.get("critical", False)),
            tags=tuple(raw.get("tags", ())),
            provenance=str(raw.get("provenance", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "suite": self.suite,
            "split": self.split,
            "inputs": dict(self.inputs),
            "expected": self.expected,
            "scorer": self.scorer,
            "critical": self.critical,
            "tags": list(self.tags),
            "provenance": self.provenance,
        }


def load_cases(path: str | Path) -> list[Case]:
    """Load and validate a JSONL case file. Case IDs must be unique."""
    cases: list[Case] = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            where = f"{path}:{lineno}: "
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CaseError(f"{where}invalid JSON ({exc.msg})") from exc
            case = Case.from_dict(raw, where=where)
            if case.id in seen:
                raise CaseError(f"{where}duplicate case id {case.id!r}")
            seen.add(case.id)
            cases.append(case)
    if not cases:
        raise CaseError(f"{path}: no cases")
    return cases


def select(
    cases: Iterable[Case], *, suite: str | None = None, split: str | None = None
) -> list[Case]:
    """Filter cases by suite and/or split."""
    return [
        c
        for c in cases
        if (suite is None or c.suite == suite) and (split is None or c.split == split)
    ]


def case_set_hash(cases: Iterable[Case]) -> str:
    """Order-independent SHA-256 over the cases' canonical JSON (tamper evidence, T5)."""
    lines = sorted(json.dumps(c.to_dict(), sort_keys=True) for c in cases)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def write_cases(path: str | Path, cases: Iterable[Case]) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c.to_dict(), sort_keys=True) + "\n")
