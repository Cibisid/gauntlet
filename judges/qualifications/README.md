# Judge qualification records

`gauntlet qualify` writes one JSON record per rubric version here. A judge may only gate when its record shows:
- Cohen's kappa ≥ 0.60 against human labels
- fail-class recall ≥ 0.80
- at least 200 labelled items

See ADR-0002.

**No records are committed yet.** They require real human labels (`gauntlet label`). Simulated labels are used only inside tests.
