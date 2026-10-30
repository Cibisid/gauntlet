# ADR-0003: Kubernetes everywhere, with a cheap cloud footprint

**Status:** Proposed · **Date:** 2026-10-30

## Context
Kubernetes appears in about 61% of the hand-read 2026 postings (cloud/K8s/IaC group), so the platform should run on it. But EKS costs about $73/month for the control plane alone, plus nodes. GPU instances cost money every hour they exist. This is a solo project with a small budget.

## Decision (proposed)
- **Local / CI:** kind cluster with a mock model server, so the full end-to-end test runs free in GitHub Actions.
- **Cloud demo:** Terraform modules that support two targets:
  - (a) **EKS**, created only for demo and benchmark windows and destroyed afterwards
  - (b) **k3s on a single EC2 instance**, for always-on staging
- **GPU:** a vLLM node created on demand (spot L4/A10G-class) for benchmark windows only.

## Consequences
- The same Helm charts run everywhere, and reviewers can reproduce the stack locally.
- The cost per month is documented and bounded by AWS Budgets alarms.
- Cold-start time for demos must be scripted (`make demo-up` / `make demo-down`).

## To decide by week 2
- Whether option (a) adds enough credibility over (b) to justify the cost.
