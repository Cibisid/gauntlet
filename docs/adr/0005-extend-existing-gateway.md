# ADR-0005: Extend the existing LLM Gateway as the data plane

**Status:** Superseded in part by ADR-0007 (the gateway now sits *behind* the Gauntlet proxy as an upstream) · **Date:** 2026-10-30

## Context
I already maintain an OpenAI-compatible LLM Gateway with multi-provider routing, MCP tools and A2A delegation. Building a new proxy would duplicate it, and reviewers would see two half-finished systems.

## Decision
Gauntlet is the control plane. The existing gateway is extended with:
- release-weighted routing
- guardrail hooks
- OpenTelemetry GenAI spans
- per-key rate limits and token budgets

The two communicate through a versioned internal API, with contract tests on both sides.

## Consequences
- The portfolio reads as one coherent system that grew, not three unrelated repos.
- Gateway changes need backward-compatible contracts.
