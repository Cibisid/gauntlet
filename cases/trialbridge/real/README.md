# Real TrialBridge cases (week 3)

This folder holds **human-written and human-labelled** cases from the real TrialBridge task. They replace the synthetic suite as the primary quality gate. The synthetic suite stays as a fast CI regression check.

## What to write
Start with 30–50 cases, then grow to 300 or more (see ADR-0006 for why size matters). For each case:

1. Write a short, de-identified patient description.
   - **Never use real patient data.** Invent it, or adapt a published example.
2. Pick 3–8 real trials from ClinicalTrials.gov (NCT IDs) that TrialBridge would retrieve for it.
3. Decide which of those trials the patient is eligible for, and note why in `rationale`.
4. Mark the split:
   - About 40% `dev`, for prompt iteration.
   - About 60% `holdout`, which only the gate sees.

## Format (one JSON object per line in `v1.jsonl`)
```json
{"id": "tb-real-0001", "suite": "quality", "split": "holdout",
 "inputs": {"payload": {"patient": {"age": 58, "conditions": ["type 2 diabetes", "hypertension"],
                                    "medications": ["metformin"], "notes": "eGFR 52; no insulin use"},
                        "trials": [{"id": "NCT0XXXXXXX", "title": "...", "criteria_text": "..."}]}},
 "expected": {"key": "eligible_trials", "items": ["NCT0XXXXXXX"]},
 "scorer": "json_set_f1", "tags": ["diabetes", "renal-threshold"],
 "provenance": "hand-labelled by Cibi 2026-11-0X; rationale: eGFR above 45 cutoff"}
```

`gauntlet.cases.load_cases` validates the file. Any schema error fails CI with the line number.
