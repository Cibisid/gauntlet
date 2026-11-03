# ADR-0008: Enforce on outputs; treat the input injection detector as a signal only

**Status:** Accepted · **Date:** 2026-11-02

## Context
The first guardrail version had two layers:
- a pattern-based prompt-injection detector on inputs
- a protected-string (canary/system prompt) filter plus PII redaction on outputs

On the synthetic security suite the detector scored 100% recall with 0/800 false positives. But that suite's 8 attack templates existed before the patterns were written, so the number was optimistic by construction.

To measure it honestly, I wrote 20 new attack phrasings and 10 tricky benign clinical notes **after freezing the patterns** (`cases/security/heldout_*.txt`). Results on that held-out set:
- **Recall: 0/20** (95% Wilson CI 0–16%)
- **False positives: 0/10** (95% CI 0–28%)

## Decision
- **The input detector is flag-only.** It is off by default (`block_on_injection: false`). It labels traces and feeds the `prompt_injection` metric for monitoring, but never blocks requests.
- **Enforcement happens on outputs.** Protected strings are blocked whatever the attack's wording, and PII is redacted before anything is returned or stored. The gate's security pack measures the *output*, which is what users see.
- **Release gating runs the full guardrail policy** through the runner, so the guarded system is what gets tested (`examples/injectable_model_guarded.yaml` passes; the unguarded one fails).
- **No tuning on the held-out set.** The held-out files are never used to tune patterns. A future classifier (a small fine-tuned model or a hosted moderation API) must report recall on a *new* held-out set.

## Consequences
- Leaks of protected strings are stopped even for novel attacks, but only for strings declared in `protected_strings`. Paraphrased leaks of secret *content* are not caught. That limitation is recorded in the threat model (T9).
- The README reports the 0/20 result rather than the flattering 100%.
