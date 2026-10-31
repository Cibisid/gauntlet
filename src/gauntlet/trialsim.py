"""A synthetic, rule-checkable version of the TrialBridge eligibility task.

This exists so the whole pipeline (cases -> runner -> gate -> rollout) can be
tested deterministically in CI without paying for model calls. It is NOT real
clinical data and not a model of real eligibility criteria. Real TrialBridge
cases with human labels replace it as the primary suite from week 3.

Task: given a patient and a list of trials, return the IDs of trials the
patient is eligible for, as ``{"eligible_trials": [...]}``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

DATA_START = "<<<DATA"
DATA_END = "DATA>>>"


def is_eligible(
    patient: Mapping[str, Any], trial: Mapping[str, Any], *, check_exclusions: bool = True
) -> bool:
    age = int(patient["age"])
    if not trial["min_age"] <= age <= trial["max_age"]:
        return False
    conditions = {c.lower() for c in patient["conditions"]}
    if trial["required_condition"].lower() not in conditions:
        return False
    if check_exclusions:
        blocked = conditions | {m.lower() for m in patient["medications"]}
        if blocked & {x.lower() for x in trial["exclusions"]}:
            return False
    return True


def eligible_ids(
    patient: Mapping[str, Any],
    trials: Sequence[Mapping[str, Any]],
    *,
    check_exclusions: bool = True,
) -> list[str]:
    return sorted(
        str(t["id"]) for t in trials if is_eligible(patient, t, check_exclusions=check_exclusions)
    )


def extract_payload(text: str) -> dict[str, Any] | None:
    """Pull the JSON payload a prompt template wraps in DATA markers."""
    start = text.find(DATA_START)
    end = text.find(DATA_END, start + 1)
    if start == -1 or end == -1:
        return None
    try:
        payload = json.loads(text[start + len(DATA_START) : end])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
