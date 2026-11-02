"""Closed-loop load generator for the proxy or any OpenAI-compatible endpoint.

For each concurrency level it runs ``duration_s`` of back-to-back requests and
reports throughput, latency percentiles and error rate. Results always record
the target, hardware note and model so numbers are never quoted without context.
"""

from __future__ import annotations

import json
import platform
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from gauntlet.gate import percentile


@dataclass(frozen=True)
class LevelResult:
    concurrency: int
    requests: int
    errors: int
    duration_s: float
    throughput_rps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


def run_level(
    send: Any, payloads: Sequence[Mapping[str, Any]], concurrency: int, duration_s: float
) -> LevelResult:
    latencies: list[float] = []
    errors = 0
    lock = threading.Lock()
    stop_at = time.perf_counter() + duration_s
    counter = 0

    def worker() -> None:
        nonlocal errors, counter
        while time.perf_counter() < stop_at:
            with lock:
                payload = payloads[counter % len(payloads)]
                counter += 1
            t0 = time.perf_counter()
            ok = send(payload)
            dt = (time.perf_counter() - t0) * 1000
            with lock:
                if ok:
                    latencies.append(dt)
                else:
                    errors += 1

    started = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - started
    done = len(latencies) + errors
    return LevelResult(
        concurrency=concurrency,
        requests=done,
        errors=errors,
        duration_s=round(elapsed, 3),
        throughput_rps=round(len(latencies) / elapsed, 2) if elapsed else 0.0,
        p50_ms=round(percentile(latencies, 50), 2),
        p95_ms=round(percentile(latencies, 95), 2),
        p99_ms=round(percentile(latencies, 99), 2),
    )


def proxy_sender(base_url: str, app: str, api_key: str, timeout_s: float = 60.0) -> Any:
    client = httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=timeout_s,
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        limits=httpx.Limits(max_connections=512, max_keepalive_connections=512),
    )

    def send(payload: Mapping[str, Any]) -> bool:
        try:
            r = client.post(f"/v1/apps/{app}/invoke", json={"inputs": payload})
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    return send


def bench(
    send: Any,
    payloads: Sequence[Mapping[str, Any]],
    levels: Sequence[int],
    duration_s: float,
    *,
    target: str,
    note: str = "",
) -> dict[str, Any]:
    results = [asdict(run_level(send, payloads, c, duration_s)) for c in levels]
    return {
        "target": target,
        "note": note,
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "duration_s_per_level": duration_s,
        "levels": results,
    }


def to_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        f"### Load test: {report['target']}",
        "",
        f"{report['machine']}. {report.get('note', '')}",
        "",
        "| Concurrency | Requests | Errors | Throughput (req/s) | p50 ms | p95 ms | p99 ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for lv in report["levels"]:
        lines.append(
            f"| {lv['concurrency']} | {lv['requests']} | {lv['errors']} | {lv['throughput_rps']} "
            f"| {lv['p50_ms']} | {lv['p95_ms']} | {lv['p99_ms']} |"
        )
    return "\n".join(lines) + "\n"


def dump(report: Mapping[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
