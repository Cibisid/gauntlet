# ADR-0004: A Release is an immutable, content-addressed bundle

**Status:** Accepted · **Date:** 2026-10-30

## Context
Behaviour changes in LLM systems come from many places: prompt text, model ID, temperature, tool list, retrieval settings, guardrail policy and routing. If these are versioned separately, nobody can say what was live when an incident happened.

## Decision
A Release is a single YAML document containing every behaviour-affecting setting. Its ID is the SHA-256 of its canonical JSON form. Releases live in git (`releases/<app>/`) and are mirrored to Postgres. The gateway routes by Release ID with weights. Traces, gate reports and audit events all reference the Release ID.

## Consequences
- Exact reproducibility of any gate or incident.
- Rollback means changing weights, never editing content.
- Secrets are never inside a Release; they are referenced by name from Secrets Manager.
