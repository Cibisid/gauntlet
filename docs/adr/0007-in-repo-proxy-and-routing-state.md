# ADR-0007: Ship a data-plane proxy in this repo; single replica until routing state is shared

**Status:** Accepted · **Date:** 2026-11-02 · Partially supersedes ADR-0005

## Context
ADR-0005 planned to extend the separate LLM Gateway repo as the data plane. Building the release routing, guardrails, metrics and admin API in a second repo would have split the tests and CI across two codebases. The canary end-to-end test (proxy, controller and model) has to run in one pipeline to be trustworthy.

## Decision
- `gauntlet.proxy` is a small FastAPI service providing:
  - `/v1/apps/{app}/invoke` with weighted stable/canary routing
  - guardrails taken from the release
  - scrypt-hashed API keys and per-key token-bucket rate limits
  - a 256 KB body limit and security headers
  - Prometheus metrics, PII-redacted sampled traces and a feedback endpoint
  - a hash-chained audit log
  - an admin API for routing, promote, rollback and windowed stats
- It talks to any OpenAI-compatible upstream. The LLM Gateway, vLLM or a hosted API can sit behind it, so the gateway's multi-provider routing is reused, not duplicated.
- Routing state lives in the pod (memory plus a JSON file) and survives restarts when the volume persists. The Kubernetes Deployment therefore runs **one replica with a Recreate strategy**.

## Consequences
- The whole platform is tested in one CI run: unit, HTTP integration, kind cluster and DAST.
- **Not highly available yet.** Running several replicas needs routing state and windowed stats in a shared store, such as Postgres for routing and Prometheus queries for stats. That work is listed as follow-up.
- The proxy's measured in-handler overhead is under 1 ms for 99.7% of requests (`benchmarks/proxy_mock_upstream.md`), so placing it in front of the gateway is cheap.
