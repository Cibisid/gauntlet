# Running Gauntlet against real models

The CI demos use a mock model. This is how to produce real numbers.

## Free path (Groq)
1. Create a free Groq account at <https://console.groq.com> and create an API key. No card is needed.
2. In GitHub, go to **Settings → Secrets and variables → Actions → New repository secret**. Name it `GAUNTLET_API_KEY` and paste the key.
3. Go to **Actions → real-model-gate → Run workflow**. The defaults compare `openai/gpt-oss-120b` (baseline) with
   `openai/gpt-oss-20b` (candidate). Both are OpenAI open-weight models served by Groq, and the question is
   "can we swap to the model that is 6× smaller and half the price?"
4. The free tier allows about 200K tokens per model per day. A full comparison is 514 gate cases per model
   (474 held-out quality cases and 40 injection cases), which is more than one day's quota. So each run does at most `limit` (260) new cases per model.
   - If the job summary says **Incomplete**, run the workflow again the next day with `resume_from_run` set to the run ID it shows.
   - Finished cases are kept. Cases that failed (quota exhausted) run again.
5. When both models reach 514/514, the summary shows the results table and the gate report.
   Everything is also in the `real-model-results` artifact.

If a model has been retired, the first step fails within seconds and lists the models that are available.

## How quotas are handled
- `--max-rpm` paces requests. A short `Retry-After` (60 s or less) is honoured.
- A long `Retry-After` means a daily quota has run out. The request fails at once instead of sleeping for hours, and `--resume` picks the case up on the next run.
- Only successful results for the **same release ID** are reused, so changing the prompt or model starts over.

## Paid path (any OpenAI-compatible API)
Set `base_url`, the model names and the list prices, set `limit` to 600, and leave `resume_from_run` blank.
At about 400 input tokens per case, small models cost well under $1 per run.

## What the numbers mean
- **holdout exact match**: the share of the 474 held-out cases where the model returned exactly the right trial set, with a 95% Wilson CI.
- **injection cases where the model leaked the canary**: how often the raw model obeyed a prompt injection and printed the protected code. The output guardrail flags and blocks these.
- **leaks served to users**: leaks that got past the guardrail. This should be 0.
- **gate verdict**: paired non-inferiority of candidate against baseline (δ = 0.03), plus security, error-rate, latency and cost checks.

Prices are the list prices passed in when the run starts. Check them on the provider's pricing page.
The cases are still **synthetic** patients and trials, so the numbers measure the models on this task, not on real clinical data.
