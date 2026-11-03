### Load test: http://127.0.0.1:8080

Linux x86_64, Python 3.13.18. Upstream: bundled mock model with a fixed 30 ms delay. Measures proxy overhead and throughput, NOT model quality or GPU serving.

| Concurrency | Requests | Errors | Throughput (req/s) | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|---|---|
| 1 | 411 | 0 | 27.4 | 36.04 | 39.29 | 42.18 |
| 8 | 2405 | 0 | 159.86 | 50.06 | 59.86 | 65.28 |
| 32 | 3904 | 5 | 250.04 | 95.96 | 145.89 | 1129.33 |

**Proxy overhead** is the time spent inside the proxy handler, excluding the upstream call. It comes from the `gauntlet_proxy_overhead_seconds` histogram over 6,720 requests:
- 99.7% took ≤ 1 ms
- 100% took ≤ 5 ms

That is well inside the design SLO of p95 < 40 ms. This figure excludes time requests spend queued in the ASGI server.

**Context:**
- **Machine:** a 2-vCPU cloud container. The load generator, the proxy (one uvicorn worker) and the mock upstream all ran on it.
- **Saturation:** at concurrency 32 the box saturated. Tail latency rose and 5 of 3,904 requests failed. Scaling out (more uvicorn workers or replicas) is expected to raise the ceiling, but that has not been measured yet.
- **Not a model benchmark:** the upstream is a mock with a fixed 30 ms delay, so these numbers say nothing about model quality or GPU serving. Real vLLM numbers need a GPU run (`infra/terraform`, `enable_gpu = true`).
