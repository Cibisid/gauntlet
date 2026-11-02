"""Human labelling: sample outputs, collect pass/fail labels, measure agreement."""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from gauntlet.cases import Case
from gauntlet.runner import CaseResult
from gauntlet.stats import cohens_kappa


@dataclass(frozen=True)
class Label:
    case_id: str
    release_id: str
    label: str  # "pass" | "fail"
    labeler: str
    note: str = ""
    labelled_at: str = ""


def sample_for_labeling(
    results: Sequence[CaseResult], *, n: int, seed: int = 0, suite: str = "quality"
) -> list[CaseResult]:
    """Stratified sample: half from perfect-score outputs, half from imperfect ones,
    so the fail class is represented even when the system is mostly right."""
    pool = [r for r in results if r.suite == suite and not r.error]
    # Sampling for labelling, not security: B311/S311 do not apply.
    rng = random.Random(seed)  # noqa: S311  # nosec B311
    good = [r for r in pool if r.score >= 1.0]
    bad = [r for r in pool if r.score < 1.0]
    rng.shuffle(good)
    rng.shuffle(bad)
    take_bad = min(len(bad), n // 2)
    picked = bad[:take_bad] + good[: n - take_bad]
    rng.shuffle(picked)
    return picked


def render_item(case: Case, result: CaseResult) -> str:
    patient_and_trials = json.dumps(dict(case.inputs), indent=2, sort_keys=True)
    return (
        f"=== {case.id} (release {result.release_id}) ===\n"
        f"TASK INPUT:\n{patient_and_trials}\n\n"
        f"MODEL OUTPUT:\n{result.output}\n"
    )


def label_interactive(
    items: Sequence[CaseResult],
    cases: Mapping[str, Case],
    *,
    labeler: str,
    out_path: str | Path,
    ask: Callable[[str], str] | None = None,
    show: Callable[[str], None] | None = None,
) -> list[Label]:
    """Ask a human to label each item pass/fail. Appends to ``out_path`` as it goes,
    so an interrupted session loses nothing. Type 'q' to stop early."""
    ask = ask or input
    show = show or print
    done = {lab.case_id for lab in load_labels(out_path)} if Path(out_path).exists() else set()
    labels: list[Label] = []
    with Path(out_path).open("a", encoding="utf-8") as fh:
        for i, res in enumerate(items, start=1):
            if res.case_id in done:
                continue
            show(f"[{i}/{len(items)}]\n" + render_item(cases[res.case_id], res))
            while True:
                answer = ask("Is this answer correct? [p]ass / [f]ail / [q]uit: ").strip().lower()
                if answer in {"p", "f", "q"}:
                    break
            if answer == "q":
                break
            note = ask("Optional note (enter to skip): ").strip()
            lab = Label(
                case_id=res.case_id,
                release_id=res.release_id,
                label="pass" if answer == "p" else "fail",
                labeler=labeler,
                note=note,
                labelled_at=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            fh.write(json.dumps(asdict(lab), sort_keys=True) + "\n")
            fh.flush()
            labels.append(lab)
    return labels


def load_labels(path: str | Path) -> list[Label]:
    with Path(path).open(encoding="utf-8") as fh:
        return [Label(**json.loads(line)) for line in fh if line.strip()]


def agreement(a: Iterable[Label], b: Iterable[Label]) -> tuple[int, float]:
    """Cohen's kappa between two labellers on the items both labelled."""
    la = {x.case_id: x.label for x in a}
    lb = {x.case_id: x.label for x in b}
    common = sorted(la.keys() & lb.keys())
    if not common:
        raise ValueError("the two label files share no items")
    return len(common), cohens_kappa([la[c] for c in common], [lb[c] for c in common])
