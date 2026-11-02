"""Measure the injection detector on held-out phrasings (see ADR-0008).

Usage: python scripts/heldout_detector_eval.py
Never tune guardrail patterns on these files; write a new held-out set instead.
"""

from pathlib import Path

from gauntlet.guardrails import evaluate_detector
from gauntlet.stats import wilson_interval

ROOT = Path(__file__).resolve().parents[1] / "cases" / "security"


def lines(name: str) -> list[str]:
    text = (ROOT / name).read_text(encoding="utf-8")
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def main() -> None:
    attacks, benign = lines("heldout_injections.txt"), lines("heldout_benign.txt")
    rep = evaluate_detector(attacks, benign)
    r_lo, r_hi = wilson_interval(rep.true_pos, len(attacks))
    f_lo, f_hi = wilson_interval(rep.false_pos, len(benign))
    print(
        f"held-out recall {rep.true_pos}/{len(attacks)} (95% CI {r_lo:.0%}-{r_hi:.0%}); "
        f"false positives {rep.false_pos}/{len(benign)} (95% CI {f_lo:.0%}-{f_hi:.0%})"
    )


if __name__ == "__main__":
    main()
