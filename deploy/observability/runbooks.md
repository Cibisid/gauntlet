# Gauntlet alert runbooks

One section per alert in `prometheus/alerts.yml`. Each alert's `runbook_url` links to the heading of the same name (GitHub lowercases heading anchors).

Rollback command used throughout: `gauntlet rollout rollback` sets the candidate release's traffic weight to 0 and sends all traffic to the baseline. Confirm it took effect on the dashboard's "Traffic weight by release" panel or with `gauntlet_release_weight` in Prometheus.

## GauntletProxyDown

**Symptom.** Prometheus cannot scrape `gauntlet-proxy:8080/metrics` for 1 minute. Every other alert is blind while this fires.

**Likely causes.** The proxy container crashed or is restarting; it is not on the same Docker network as Prometheus; the `/metrics` endpoint was disabled or moved.

**Immediate actions.**
1. `docker compose ps` and `docker compose logs gauntlet-proxy --tail 200`.
2. From the Prometheus container: `wget -qO- http://gauntlet-proxy:8080/metrics | head`.
3. Check the Prometheus Targets page (http://localhost:9090/targets) for the scrape error.

**Follow-up.** Add a container healthcheck and restart policy if missing; find the crash cause in logs.

## GauntletHighErrorRate

**Symptom.** More than 2% of a release's requests ended with `status="error"` over 5 minutes. Guardrail blocks are counted separately and do not trigger this.

**Likely causes.** Upstream model backend errors or timeouts; a bad prompt template or config in the release; output parsing failures in a new candidate; rate limits from the model provider.

**Immediate actions.**
1. Check which release is affected. If it is the candidate, run `gauntlet rollout rollback` straight away.
2. If the baseline is also failing, the problem is upstream: check backend health and provider status, not the release.
3. Look at proxy logs for the dominant error class.

**Follow-up.** Add a regression case for the failure to the gate's case set; make sure the gate would have caught it before rollout.

## GauntletLatencySLOBreach

**Symptom.** p95 request latency for a release is above 1.5s over 5 minutes.

**Likely causes.** Larger model or longer prompts in the candidate; higher `max_tokens` producing longer outputs (check the "Tokens per second" panel); backend saturation or cold starts; retries inside the proxy.

**Immediate actions.**
1. Compare p95 across releases on the latency panel. If only the candidate breaches, run `gauntlet rollout rollback`.
2. If all releases breach, check backend load and request rate; consider lowering the candidate weight to shed load.

**Follow-up.** Add a latency budget check to the release gate; review token limits in the release config.

## GauntletCanaryLeak

**Symptom.** The `canary_leak` guardrail blocked at least one response in the last 5 minutes. The model tried to output a planted canary secret, which means system-prompt or context exfiltration was attempted and nearly succeeded. Severity: critical.

**Likely causes.** A successful prompt-injection payload in user input or retrieved content; a candidate prompt that weakened instructions; a guardrail regression elsewhere that let the injection through to the model.

**Immediate actions.**
1. Run `gauntlet rollout rollback` if the leak is on the candidate release.
2. Pull the blocked requests from proxy logs (by release and time) and keep them as evidence.
3. Check the `prompt_injection` series on the "Guardrail blocks by check" panel: a leak with no injection block means the input detector missed it.
4. Rotate any real secret that shares a path with the canary.

**Follow-up.** Add the offending inputs as adversarial cases to the gate; write a short incident note.

## GauntletOnlineScoreDrop

**Symptom.** The rolling online quality score for a release that is receiving traffic has stayed below 0.9 for 10 minutes.

**Likely causes.** Candidate quality regression the offline gate did not catch (distribution shift between synthetic cases and live traffic); judge or scorer drift; a change in the live input mix.

**Immediate actions.**
1. If the candidate's score is below the baseline's, run `gauntlet rollout rollback`.
2. If both releases dropped together, suspect the input mix or the scorer itself, not the release; do not roll back blindly.

**Follow-up.** Sample low-scoring live requests and add them to the case set; recheck the gate's thresholds against what was seen online.

## GauntletRollbackHappened

**Symptom.** `gauntlet_rollbacks_total` went up in the last 10 minutes. Severity: info.

**Likely causes.** An automatic rollback triggered by the rollout controller, or a manual `gauntlet rollout rollback`.

**Immediate actions.**
1. Confirm the candidate's weight is now 0 on the "Traffic weight by release" panel.
2. Check which other alert fired just before it (error rate, latency, canary leak, online score) to find the trigger.

**Follow-up.** Record why the rollback happened before the candidate is retried; fix and re-gate.

## GauntletCostBurnRate

**Symptom.** Total model spend across releases is above the configured budget (default $5/hour, set in the expression in `alerts.yml`) for 15 minutes.

**Likely causes.** Traffic spike; a candidate using a pricier model or longer prompts; runaway output length; a client looping (check `gauntlet_rate_limited_total` by client).

**Immediate actions.**
1. Check "Cost per request" by release. If the candidate is much higher, lower its weight or run `gauntlet rollout rollback`.
2. If cost per request is flat but request rate rose, find the client driving it and tighten its rate limit.

**Follow-up.** Add a cost-per-request budget to the release gate; adjust the alert threshold if the budget changed.
