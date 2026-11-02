"""Gauntlet data-plane proxy.

Serves an application (``POST /v1/apps/{app}/invoke``) by rendering the active
release's prompt, calling an OpenAI-compatible upstream (vLLM, a hosted API, or
the LLM Gateway), and applying the release's guardrails. Traffic is split
between a *stable* and an optional *canary* release by weight; the rollout
controller changes the weights through the admin API.

Cross-cutting concerns: API-key auth (scrypt-hashed keys), per-key rate
limits, request size limits, Prometheus metrics, JSON logs with trace IDs,
PII-redacted trace sampling, and a hash-chained audit log for admin actions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from gauntlet.guardrails import (
    BLOCKED_OUTPUT,
    GuardrailPolicy,
    check_input,
    check_output,
    redact_pii,
)
from gauntlet.prompts import PromptError, render_messages
from gauntlet.release import ReleaseError, release_id, validate
from gauntlet.runner import request_cost
from gauntlet.scorers import extract_json_object

log = logging.getLogger("gauntlet.proxy")
MAX_BODY_BYTES = 256 * 1024
WINDOW_EVENTS = 50_000


# ---------------------------------------------------------------- key hashing


def hash_key(key: str, *, salt: bytes | None = None) -> str:
    """scrypt hash in the form ``scrypt$<salt hex>$<hash hex>``."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(key.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_key(key: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hash_key(key, salt=bytes.fromhex(salt_hex)).split("$")[2]
    return hmac.compare_digest(candidate, digest_hex)


class KeyStore:
    """Verifies API keys; caches successful checks by SHA-256 so scrypt runs once per key."""

    def __init__(self, hashed: Mapping[str, str]) -> None:
        self._hashed = dict(hashed)
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()

    def identify(self, key: str) -> str | None:
        fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()
        with self._lock:
            if fingerprint in self._cache:
                return self._cache[fingerprint]
        for name, stored in self._hashed.items():
            if verify_key(key, stored):
                with self._lock:
                    self._cache[fingerprint] = name
                return name
        return None


def parse_key_list(raw: str) -> dict[str, str]:
    """``name:scrypt$..$..,name2:...`` -> {name: hash}."""
    out: dict[str, str] = {}
    for item in filter(None, (x.strip() for x in raw.split(","))):
        name, _, hashed = item.partition(":")
        if name and hashed:
            out[name] = hashed
    return out


# ---------------------------------------------------------------- rate limiting


class RateLimiter:
    """Token bucket per client: ``rpm`` requests per minute, burst of ``rpm // 4 + 1``."""

    def __init__(self, rpm: int) -> None:
        self.rate = rpm / 60.0
        self.capacity = max(1.0, rpm / 4 + 1)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, client: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens, last = self._buckets.get(client, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens < 1.0:
                self._buckets[client] = (tokens, now)
                return False
            self._buckets[client] = (tokens - 1.0, now)
            return True


# ---------------------------------------------------------------- audit log


class AuditLog:
    """Append-only JSONL where each entry carries the hash of the previous one."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._last = "0" * 64
        if path.exists():
            lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if lines:
                self._last = json.loads(lines[-1])["hash"]

    def append(self, actor: str, action: str, detail: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            entry = {
                "ts": time.time(),
                "actor": actor,
                "action": action,
                "detail": dict(detail),
                "prev": self._last,
            }
            digest = _entry_hash(entry)
            entry["hash"] = digest
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
            self._last = digest
            return entry


def _entry_hash(entry: Mapping[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def verify_audit_log(path: str | Path) -> tuple[bool, int, str]:
    """Check the hash chain. Returns (ok, entries checked, message)."""
    prev = "0" * 64
    n = 0
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        entry = json.loads(line)
        if entry.get("prev") != prev:
            return False, n, f"entry {n}: chain broken (prev hash mismatch)"
        if entry.get("hash") != _entry_hash(entry):
            return False, n, f"entry {n}: content was modified"
        prev = entry["hash"]
    return True, n, "ok"


# ---------------------------------------------------------------- routing state


@dataclass
class ReleaseSlot:
    doc: dict[str, Any]
    id: str
    policy: GuardrailPolicy | None

    @classmethod
    def of(cls, doc: Mapping[str, Any]) -> ReleaseSlot:
        validate(doc)
        return cls(dict(doc), release_id(doc), GuardrailPolicy.from_release(doc))


@dataclass
class Routing:
    app: str
    stable: ReleaseSlot | None = None
    canary: ReleaseSlot | None = None
    canary_weight: float = 0.0
    changed_at: float = 0.0

    def weights(self) -> dict[str, float]:
        out: dict[str, float] = {}
        if self.stable:
            out[self.stable.id] = 1.0 - (self.canary_weight if self.canary else 0.0)
        if self.canary:
            out[self.canary.id] = self.canary_weight
        return out

    def pick(self) -> ReleaseSlot:
        if self.stable is None:
            raise HTTPException(503, "no release is deployed")
        if self.canary and secrets.randbelow(1_000_000) < self.canary_weight * 1_000_000:
            return self.canary
        return self.stable

    def to_json(self) -> dict[str, Any]:
        return {
            "app": self.app,
            "stable": self.stable.doc if self.stable else None,
            "canary": self.canary.doc if self.canary else None,
            "canary_weight": self.canary_weight,
            "weights": self.weights(),
            "changed_at": self.changed_at,
        }


# ---------------------------------------------------------------- windowed stats


@dataclass
class Event:
    ts: float
    release: str
    status: str  # ok | error | blocked
    latency_s: float
    online_score: float
    flags: tuple[str, ...] = field(default_factory=tuple)


def window_stats(events: list[Event], since: float) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    by_release: dict[str, list[Event]] = {}
    for e in events:
        if e.ts >= since:
            by_release.setdefault(e.release, []).append(e)
    for rel, evs in by_release.items():
        lat = sorted(e.latency_s for e in evs if e.status != "error")
        p95 = lat[max(0, int(0.95 * len(lat) + 0.999999) - 1)] if lat else 0.0
        out[rel] = {
            "requests": float(len(evs)),
            "errors": float(sum(e.status == "error" for e in evs)),
            "blocked": float(sum(e.status == "blocked" for e in evs)),
            "canary_leaks": float(sum("canary_leak" in e.flags for e in evs)),
            "p95_latency_s": p95,
            "online_score": sum(e.online_score for e in evs) / len(evs),
        }
    return out


# ---------------------------------------------------------------- settings


@dataclass
class Settings:
    upstream_base_url: str
    app: str = "trialbridge"
    state_dir: Path = Path("state")
    api_keys: dict[str, str] = field(default_factory=dict)
    admin_key_hash: str = ""
    allow_anonymous: bool = False
    rate_limit_rpm: int = 600
    trace_sample: float = 1.0
    upstream_timeout_s: float = 60.0
    upstream_api_key: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            upstream_base_url=env.get("GAUNTLET_UPSTREAM", "http://127.0.0.1:8089/v1"),
            app=env.get("GAUNTLET_APP", "trialbridge"),
            state_dir=Path(env.get("GAUNTLET_STATE_DIR", "state")),
            api_keys=parse_key_list(env.get("GAUNTLET_API_KEY_HASHES", "")),
            admin_key_hash=env.get("GAUNTLET_ADMIN_KEY_HASH", ""),
            allow_anonymous=env.get("GAUNTLET_ALLOW_ANONYMOUS", "false").lower() == "true",
            rate_limit_rpm=int(env.get("GAUNTLET_RATE_LIMIT_RPM", "600")),
            trace_sample=float(env.get("GAUNTLET_TRACE_SAMPLE", "1.0")),
            upstream_timeout_s=float(env.get("GAUNTLET_UPSTREAM_TIMEOUT_S", "60")),
            upstream_api_key=env.get("GAUNTLET_UPSTREAM_API_KEY", ""),
        )


# ---------------------------------------------------------------- metrics


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        r = self.registry
        self.requests = Counter("gauntlet_requests", "Requests", ["release", "status"], registry=r)
        self.latency = Histogram(
            "gauntlet_request_latency_seconds", "End-to-end latency", ["release"], registry=r,
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 1.5, 2.5, 5, 10),
        )  # fmt: skip
        self.overhead = Histogram(
            "gauntlet_proxy_overhead_seconds", "Proxy time excluding upstream", registry=r,
            buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.04, 0.05, 0.1, 0.25),
        )  # fmt: skip
        self.blocks = Counter(
            "gauntlet_guardrail_blocks", "Guardrail interventions", ["release", "check"], registry=r
        )
        self.tokens = Counter("gauntlet_tokens", "Tokens", ["release", "direction"], registry=r)
        self.cost = Counter("gauntlet_cost_usd", "Cost in USD", ["release"], registry=r)
        self.online = Gauge(
            "gauntlet_online_score", "Rolling online score", ["release"], registry=r
        )
        self.weight = Gauge("gauntlet_release_weight", "Traffic share", ["release"], registry=r)
        self.rollbacks = Counter("gauntlet_rollbacks", "Rollbacks", registry=r)
        self.rate_limited = Counter(
            "gauntlet_rate_limited", "Rate-limited requests", ["client"], registry=r
        )


def online_score(text: str, flags: tuple[str, ...]) -> float:
    """Reference-free online check: well-formed answer and no guardrail block."""
    if "canary_leak" in flags or "input_too_large" in flags:
        return 0.0
    obj = extract_json_object(text)
    return 1.0 if obj is not None and isinstance(obj.get("eligible_trials"), list) else 0.0


# ---------------------------------------------------------------- app


def create_app(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    headers = (
        {"Authorization": f"Bearer {settings.upstream_api_key}"}
        if settings.upstream_api_key
        else {}
    )
    client = httpx.AsyncClient(
        base_url=settings.upstream_base_url.rstrip("/") + "/",
        timeout=settings.upstream_timeout_s,
        headers=headers,
        transport=transport,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await client.aclose()

    app = FastAPI(
        title="Gauntlet proxy", version="1.0.0", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    metrics = Metrics()
    keys = KeyStore(settings.api_keys)
    limiter = RateLimiter(settings.rate_limit_rpm)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(settings.state_dir / "audit.jsonl")
    trace_path = settings.state_dir / "traces.jsonl"
    trace_lock = threading.Lock()
    routing = Routing(app=settings.app)
    routing_path = settings.state_dir / "routing.json"
    events: deque[Event] = deque(maxlen=WINDOW_EVENTS)
    online_window: dict[str, deque[float]] = {}

    def save_routing() -> None:
        routing.changed_at = time.time()
        routing_path.write_text(json.dumps(routing.to_json(), sort_keys=True), encoding="utf-8")
        for rel, w in routing.weights().items():
            metrics.weight.labels(rel).set(w)

    if routing_path.exists():
        saved = json.loads(routing_path.read_text(encoding="utf-8"))
        if saved.get("stable"):
            routing.stable = ReleaseSlot.of(saved["stable"])
        if saved.get("canary"):
            routing.canary = ReleaseSlot.of(saved["canary"])
            routing.canary_weight = float(saved.get("canary_weight", 0.0))
        routing.changed_at = float(saved.get("changed_at", 0.0))

    app.state.routing = routing
    app.state.metrics = metrics

    @app.middleware("http")
    async def envelope(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = request.headers.get("x-trace-id") or secrets.token_hex(8)
        request.state.trace_id = trace_id
        length = int(request.headers.get("content-length") or 0)
        if length > MAX_BODY_BYTES:
            return JSONResponse({"error": "request too large"}, status_code=413)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        log.info(json.dumps({
            "trace_id": trace_id, "method": request.method, "path": request.url.path,
            "status": response.status_code, "ms": round((time.perf_counter() - started) * 1000, 2),
        }))  # fmt: skip
        return response

    def client_name(request: Request) -> str:
        auth = request.headers.get("authorization", "")
        key = auth[7:] if auth.lower().startswith("bearer ") else ""
        if key:
            name = keys.identify(key)
            if name:
                return name
        if settings.allow_anonymous and not key:
            return "anonymous"
        raise HTTPException(401, "invalid or missing API key")

    def require_admin(request: Request) -> str:
        auth = request.headers.get("authorization", "")
        key = auth[7:] if auth.lower().startswith("bearer ") else ""
        if not settings.admin_key_hash or not key or not verify_key(key, settings.admin_key_hash):
            raise HTTPException(401, "admin key required")
        return "admin"

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        ready = routing.stable is not None
        return JSONResponse({"ready": ready}, status_code=200 if ready else 503)

    @app.get("/metrics")
    async def metrics_endpoint() -> Response:
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/apps/{app_name}/invoke")
    async def invoke(app_name: str, request: Request) -> JSONResponse:
        who = client_name(request)
        if not limiter.allow(who):
            metrics.rate_limited.labels(who).inc()
            raise HTTPException(429, "rate limit exceeded")
        if app_name != settings.app:
            raise HTTPException(404, "unknown app")
        try:
            body = await request.json()
            inputs = body["inputs"]
            if not isinstance(inputs, dict):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, "body must be JSON with an 'inputs' object") from None

        started = time.perf_counter()
        slot = routing.pick()
        rel = slot.id
        flags: list[str] = []
        try:
            messages = render_messages(slot.doc["prompt"], inputs)
        except PromptError as exc:
            raise HTTPException(400, f"inputs do not fit the release prompt: {exc}") from None

        upstream_s = 0.0
        usage: dict[str, int] = {}
        status = "ok"
        text = ""
        if slot.policy is not None:
            iv = check_input(messages, slot.policy)
            flags.extend(iv.reasons)
            if iv.blocked:
                status, text = "blocked", BLOCKED_OUTPUT
        if status == "ok":
            payload = {"model": slot.doc["model"]["name"], "messages": messages}
            for k in ("temperature", "max_tokens", "top_p", "seed"):
                if k in slot.doc.get("params", {}):
                    payload[k] = slot.doc["params"][k]
            t0 = time.perf_counter()
            try:
                resp = await client.post("chat/completions", json=payload)
                upstream_s = time.perf_counter() - t0
                if resp.status_code != 200:
                    raise httpx.HTTPStatusError("upstream", request=resp.request, response=resp)
                data = resp.json()
                text = str(data["choices"][0]["message"]["content"] or "")
                usage = data.get("usage") or {}
            except (httpx.HTTPError, KeyError, IndexError, ValueError):
                upstream_s = time.perf_counter() - t0
                status = "error"
        if status == "ok" and slot.policy is not None:
            ov = check_output(text, slot.policy)
            flags.extend(ov.reasons)
            text = ov.text
            if ov.blocked:
                status = "blocked"

        total_s = time.perf_counter() - started
        score = 0.0 if status == "error" else online_score(text, tuple(flags))
        metrics.requests.labels(rel, status).inc()
        if status != "error":
            metrics.latency.labels(rel).observe(total_s)
        metrics.overhead.observe(max(0.0, total_s - upstream_s))
        for f in flags:
            if f in {"canary_leak", "pii_output", "input_too_large", "prompt_injection"}:
                metrics.blocks.labels(rel, f).inc()
        in_tok, out_tok = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        metrics.tokens.labels(rel, "input").inc(in_tok)
        metrics.tokens.labels(rel, "output").inc(out_tok)
        metrics.cost.labels(rel).inc(request_cost(slot.doc["model"], in_tok, out_tok))
        win = online_window.setdefault(rel, deque(maxlen=200))
        win.append(score)
        metrics.online.labels(rel).set(sum(win) / len(win))
        events.append(Event(time.time(), rel, status, total_s, score, tuple(flags)))

        trace_id = request.state.trace_id
        if secrets.randbelow(1_000_000) < settings.trace_sample * 1_000_000:
            user_text, _ = redact_pii(messages[-1]["content"])
            record = {
                "ts": time.time(), "trace_id": trace_id, "release_id": rel, "client": who,
                "status": status, "flags": flags, "latency_s": round(total_s, 4),
                "upstream_s": round(upstream_s, 4), "input_tokens": in_tok,
                "output_tokens": out_tok, "online_score": score, "input": user_text,
                "inputs": inputs if not flags else None, "output": text,
            }  # fmt: skip
            with trace_lock, trace_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")

        if status == "error":
            raise HTTPException(502, "upstream model error")
        return JSONResponse(
            {"output": text, "release_id": rel, "trace_id": trace_id, "flags": flags}
        )

    @app.post("/v1/feedback")
    async def feedback(request: Request) -> dict[str, str]:
        who = client_name(request)
        body = await request.json()
        rating = body.get("rating")
        if rating not in {"up", "down"} or not isinstance(body.get("trace_id"), str):
            raise HTTPException(400, "need trace_id and rating 'up' or 'down'")
        record = {"ts": time.time(), "trace_id": body["trace_id"], "rating": rating,
                  "note": str(body.get("note", ""))[:500], "client": who}  # fmt: skip
        with trace_lock, (settings.state_dir / "feedback.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return {"status": "recorded"}

    @app.get("/admin/routing")
    async def get_routing(request: Request) -> dict[str, Any]:
        require_admin(request)
        return routing.to_json()

    @app.put("/admin/routing")
    async def put_routing(request: Request) -> dict[str, Any]:
        actor = require_admin(request)
        body = await request.json()
        try:
            stable = ReleaseSlot.of(body["stable"]) if body.get("stable") else routing.stable
            canary = ReleaseSlot.of(body["canary"]) if body.get("canary") else None
            weight = float(body.get("canary_weight", 0.0))
        except (ReleaseError, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(400, f"invalid routing: {exc}") from None
        if not 0.0 <= weight <= 1.0:
            raise HTTPException(400, "canary_weight must be within [0, 1]")
        if stable is None:
            raise HTTPException(400, "a stable release is required")
        routing.stable, routing.canary = stable, canary
        routing.canary_weight = weight if canary else 0.0
        save_routing()
        audit.append(actor, "set_routing", {"weights": routing.weights(),
                                            "reason": str(body.get("reason", ""))})  # fmt: skip
        return routing.to_json()

    @app.post("/admin/promote")
    async def promote(request: Request) -> dict[str, Any]:
        actor = require_admin(request)
        if routing.canary is None:
            raise HTTPException(409, "no canary to promote")
        old = routing.stable.id if routing.stable else None
        routing.stable, routing.canary, routing.canary_weight = routing.canary, None, 0.0
        save_routing()
        audit.append(actor, "promote", {"from": old, "to": routing.stable.id})
        return routing.to_json()

    @app.post("/admin/rollback")
    async def rollback(request: Request) -> dict[str, Any]:
        actor = require_admin(request)
        body = await request.json() if int(request.headers.get("content-length") or 0) else {}
        if routing.canary is None:
            raise HTTPException(409, "no canary to roll back")
        dropped = routing.canary.id
        if routing.canary_weight > 0:
            metrics.weight.labels(dropped).set(0.0)
        routing.canary, routing.canary_weight = None, 0.0
        save_routing()
        metrics.rollbacks.inc()
        audit.append(actor, "rollback", {"release": dropped, "reason": str(body.get("reason", ""))})
        return routing.to_json()

    @app.get("/admin/stats")
    async def stats(request: Request, since: float = 0.0) -> dict[str, Any]:
        require_admin(request)
        return {"now": time.time(), "releases": window_stats(list(events), since),
                "weights": routing.weights()}  # fmt: skip

    app.state.audit = audit
    app.state.events = events
    return app


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uvicorn.run(create_app(Settings.from_env()), host=host, port=port, log_level="warning")
