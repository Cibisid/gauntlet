# Threat Model (STRIDE) — v0.1

**Scope:** LLM Gateway (data plane), Gauntlet control plane, eval store, CI/CD pipeline, vLLM node.
**Method:** STRIDE per trust boundary, mapped to the OWASP Top 10 for LLM Applications (2026) and the OWASP Top 10 for Agentic Applications.
**Status:** initial draft. Each threat gets an owner control, a test, and a status in `docs/security-report.md`.

## Trust boundaries
1. Internet client → Gateway
2. Gateway → model providers / vLLM
3. Gateway → tools (MCP servers) and retrieved documents (untrusted content)
4. Admin / CI → control plane (release promotion, rollback)
5. Services → Postgres / S3 / Secrets Manager
6. GitHub → AWS (deploy credentials)

## Threats

| # | STRIDE | Boundary | Threat | Planned control | Test |
|---|---|---|---|---|---|
| T1 | Spoofing | 1 | Stolen or guessed API key | Hashed scoped keys, rotation, per-key rate limits | Auth integration tests, ZAP |
| T2 | Spoofing | 4 | Unauthorised release promotion | OIDC SSO + RBAC, signed audit events | Authz tests per role |
| T3 | Tampering | 3 | Indirect prompt injection via tool output or a retrieved doc | Untrusted-content tagging, tool allow-list per Release, output policy checks | Security pack: indirect injection |
| T4 | Tampering | 6 | Poisoned dependency or image in CI | Pinned dependencies, pip-audit/OSV, Trivy, SBOM, image signing | CI gates |
| T5 | Tampering | 4 | Case-set tampering to make a bad release pass | Case sets versioned in git with review, holdout hashed and access-restricted | Hash check in gate |
| T6 | Repudiation | 4 | Who promoted or rolled back? | Append-only audit log with actor, release and reason | Audit log tests |
| T7 | Info disclosure | 1→2 | PII in prompts leaks to traces or third-party providers | PII redaction before trace storage, provider data-retention settings, encryption at rest | Redaction unit tests and pack |
| T8 | Info disclosure | 3 | Agent exfiltrates data through a tool (URL/email/webhook) | Egress allow-list, write tools need policy approval, excessive-agency pack | Security pack: exfiltration |
| T9 | Info disclosure | 1 | System-prompt or secret extraction | No secrets in prompts, extraction pack, output filters | Security pack: extraction |
| T10 | DoS | 1→2 | Unbounded consumption (long inputs, loops) | Token budgets, max tool-call depth, timeouts, rate limits | Load and abuse tests |
| T11 | DoS | 2 | GPU node saturation | Admission control and queue limits on vLLM, shedding to API fallback | k6 overload test |
| T12 | Elevation | 3 | Agent escalates privileges via an over-permissioned tool | Least-privilege tool credentials, per-tool scopes | Excessive-agency pack |
| T13 | Elevation | 5/6 | Over-broad IAM role | Least-privilege IAM per service, GitHub OIDC, no static keys | IAM policy lint (checkov/tfsec) |

## Assumptions
- Model providers are trusted to honour their published data policies; this is not verified.
- Single tenant. Multi-tenant isolation is out of scope; see design §2.
