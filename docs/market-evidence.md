# Why this project — market evidence (collected 2026-10-30)

This note explains, with data, why Gauntlet targets evaluation, guardrails, release engineering and inference cost rather than another RAG app. The raw data is in `docs/research/`.

## Data collected
1. **Career-board scan: 1,402 AI/ML engineering job descriptions** from about 95 companies' public Greenhouse, Lever and Ashby boards (AI labs, infrastructure companies, fintech, product companies). Titles were filtered to engineering roles with ML/AI terms, and the full description text was keyword-tagged.
2. **63 hand-read postings** on LinkedIn (US 24, India 17, Nordics 6, Netherlands 5, Germany 4, Poland 4, Ireland 3), coded against a fixed tag vocabulary.
3. **Handshake** counts with and without the "open to US visa sponsorship" filter.

## Findings

**Share of career-board descriptions mentioning each theme (n = 1,402):**

| Theme | All | Titles without Senior/Staff/Lead |
|---|---|---|
| Evaluation / benchmarking | 63% | 63% |
| LLMs / GenAI | 60% | 60% |
| Distributed systems | 50% | 45% |
| Agents / tool use | 47% | 47% |
| Inference / serving | 46% | 39% |
| Safety / security / abuse | 42% | 49% |
| Observability / on-call | 41% | 32% |
| Training / fine-tuning | 29% | 32% |
| RAG / retrieval | 28% | 26% |

**Hand-read postings (n = 63), share requiring each theme:**

| Theme | All | US | EU | India |
|---|---|---|---|---|
| LLM / RAG application | 66% | 62% | 63% | 76% |
| CI/CD and MLOps | 65% | 45% | 68% | 88% |
| Cloud / Kubernetes / IaC | 61% | 58% | 63% | 64% |
| Evaluation / quality gates | 55% | 62% | 59% | 41% |
| Cost / latency | 49% | 54% | 40% | 52% |
| Agents / MCP | 47% | 41% | 50% | 52% |
| Observability / drift / on-call | 47% | 50% | 50% | 41% |
| Guardrails / security | 33% | 33% | 18% | 52% |
| Inference / GPU | 30% | 37% | 22% | 29% |

**Other observations:**
- **Seniority.** Only about 4% of career-board titles are explicitly entry level, and about 55% are Senior or higher. Of the hand-read postings that state a minimum, 28 of 46 accept 3 years or less.
- **Competition.** The median posting showed about 240 applicants, of whom 60–80% were entry level by LinkedIn's classification.
- **Sponsorship on Handshake.** 37 of 934 "machine learning engineer" and 144 of 3,707 "software engineer" postings are flagged open to US visa sponsorship (about 4%).

## Limitations
- Keyword tagging over-counts broad terms ("evaluation", "safety", "cost").
- Titles without a seniority word are not necessarily mid-level.
- The career-board sample leans toward AI-native companies that use Greenhouse, Lever or Ashby. Big Tech and large banks use other applicant-tracking systems and are covered only through LinkedIn.
- The LinkedIn sample is a purposive sample, not a random one.
