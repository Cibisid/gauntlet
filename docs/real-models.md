# Running Gauntlet against real models

The CI demos use a mock model. This is how to produce real numbers.

## Free path (Groq, about 5 minutes of setup)
1. Create a free account at <https://console.groq.com> and create an API key. No card is needed.
2. In the GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**.
   Name it `GAUNTLET_API_KEY` and paste the key.
3. **Actions → real-model-gate → Run workflow.** The defaults compare
   `meta-llama/llama-4-scout-17b-16e-instruct` (baseline) with `llama-3.1-8b-instant` (candidate).
   This is the question "can we swap to the smaller, cheaper model?"
4. Wait about 75 minutes. Both models run in parallel at 12 requests/min to stay under free-tier limits.
   The job summary shows the results table and the gate report. Everything is also in the `real-model-results` artifact.

One run is about 840 requests and 350K tokens per model, which fits the default models' free daily quota once per day.
If a model has been retired, the first step fails and lists the models that are available. Pick one and re-run.

## Paid path (any OpenAI-compatible API)
Set `base_url`, the model names and the list prices when you start the run. At about 400 input tokens per case,
one model costs roughly `840 × 400 × input price per token` plus a small amount for output. For small models this is well under $1.
Raise `max_rpm` if your tier allows it.

## What the numbers mean
- **holdout exact match** — share of the 474 held-out cases where the model returned exactly the right trial set, with a 95% Wilson CI.
- **injection cases where the model leaked the canary** — how often the raw model obeyed a prompt injection and printed the protected code. The output guardrail flags and blocks these.
- **leaks served to users** — leaks that got past the guardrail. This should be 0.
- **gate verdict** — paired non-inferiority of the candidate against the baseline (δ = 0.03), plus security, error-rate, latency and cost checks.

The cases are still **synthetic** patients and trials, so these numbers measure the models on this task, not on real clinical data.
