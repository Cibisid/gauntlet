"""Canary rollout controller with automatic rollback.

The controller only reads windowed stats from the proxy and changes weights
through its admin API, so the proxy stays the single source of truth.

Online checks catch what offline gates cannot see (live traffic, upstream
errors, latency, guardrail trips). Quality regressions on labelled cases are
the offline gate's job; this controller assumes the candidate already passed it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

STEPS = (0.01, 0.10, 0.50, 1.0)


@dataclass(frozen=True)
class RolloutPolicy:
    steps: tuple[float, ...] = STEPS
    min_requests: int = 50
    max_error_rate: float = 0.02
    max_p95_latency_s: float = 1.5
    max_canary_leaks: int = 0
    max_online_score_drop: float = 0.05

    @classmethod
    def from_release(cls, release: Mapping[str, Any]) -> RolloutPolicy:
        raw = dict(release.get("rollout", {}))
        budgets = release.get("budgets", {})
        if "p95_latency_ms" in budgets and "max_p95_latency_s" not in raw:
            raw["max_p95_latency_s"] = float(budgets["p95_latency_ms"]) / 1000
        if "steps" in raw:
            raw["steps"] = tuple(float(s) for s in raw["steps"])
        return cls(**raw)


@dataclass(frozen=True)
class Decision:
    action: str  # hold | advance | promote | rollback | idle
    reason: str
    next_weight: float | None = None


def decide(
    policy: RolloutPolicy,
    weight: float,
    canary: Mapping[str, float] | None,
    stable: Mapping[str, float] | None,
) -> Decision:
    """Pure decision function, unit-tested without any network."""
    if canary is None or canary.get("requests", 0) == 0:
        return Decision("hold", "no canary traffic in this window yet")
    n = canary["requests"]
    if canary.get("canary_leaks", 0) > policy.max_canary_leaks:
        return Decision(
            "rollback", f"{int(canary['canary_leaks'])} protected-string leak(s) blocked"
        )
    errors = canary.get("errors", 0) / n
    if n >= 10 and errors > policy.max_error_rate:
        return Decision("rollback", f"error rate {errors:.1%} > {policy.max_error_rate:.0%}")
    if n < policy.min_requests:
        return Decision("hold", f"{int(n)}/{policy.min_requests} requests at {weight:.0%}")
    if canary.get("p95_latency_s", 0) > policy.max_p95_latency_s:
        return Decision(
            "rollback",
            f"p95 {canary['p95_latency_s'] * 1000:.0f} ms > "
            f"{policy.max_p95_latency_s * 1000:.0f} ms",
        )
    if stable and stable.get("requests", 0) >= 10:
        drop = stable["online_score"] - canary["online_score"]
        if drop > policy.max_online_score_drop:
            return Decision("rollback", f"online score {drop:.3f} below stable")
    later = [s for s in policy.steps if s > weight + 1e-9]
    if not later:
        return Decision("promote", f"healthy at {weight:.0%}; promoting to stable")
    return Decision("advance", f"healthy at {weight:.0%} over {int(n)} requests", later[0])


class ProxyAdmin:
    """Thin client for the proxy's admin API."""

    def __init__(self, base_url: str, admin_key: str, *, client: httpx.Client | None = None):
        self._c = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=30)
        self._h = {"Authorization": f"Bearer {admin_key}"}

    def _req(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        resp = self._c.request(method, path, headers=self._h, **kw)
        resp.raise_for_status()
        out: dict[str, Any] = resp.json()
        return out

    def routing(self) -> dict[str, Any]:
        return self._req("GET", "/admin/routing")

    def set_routing(self, **body: Any) -> dict[str, Any]:
        return self._req("PUT", "/admin/routing", json=body)

    def rollback(self, reason: str) -> dict[str, Any]:
        return self._req("POST", "/admin/rollback", json={"reason": reason})

    def promote(self) -> dict[str, Any]:
        return self._req("POST", "/admin/promote")

    def stats(self, since: float) -> dict[str, Any]:
        return self._req("GET", "/admin/stats", params={"since": since})


def start(admin: ProxyAdmin, candidate: Mapping[str, Any], policy: RolloutPolicy) -> dict[str, Any]:
    current = admin.routing()
    return admin.set_routing(
        stable=current["stable"],
        canary=dict(candidate),
        canary_weight=policy.steps[0],
        reason="rollout started",
    )


def tick(admin: ProxyAdmin, policy: RolloutPolicy) -> Decision:
    """Evaluate the current step once and apply the decision."""
    routing = admin.routing()
    if not routing.get("canary"):
        return Decision("idle", "no canary deployed")
    weights = routing["weights"]
    stable_id = next(k for k in weights if k != _canary_id(routing))
    canary_id = _canary_id(routing)
    stats = admin.stats(since=routing["changed_at"])["releases"]
    decision = decide(policy, routing["canary_weight"], stats.get(canary_id), stats.get(stable_id))
    if decision.action == "rollback":
        admin.rollback(decision.reason)
    elif decision.action == "promote":
        admin.promote()
    elif decision.action == "advance" and decision.next_weight is not None:
        admin.set_routing(
            stable=routing["stable"],
            canary=routing["canary"],
            canary_weight=decision.next_weight,
            reason=decision.reason,
        )
    return decision


def _canary_id(routing: Mapping[str, Any]) -> str:
    from gauntlet.release import release_id

    return release_id(routing["canary"])


def watch(
    admin: ProxyAdmin,
    policy: RolloutPolicy,
    *,
    interval_s: float = 10.0,
    timeout_s: float = 3600.0,
    on_decision: Callable[[Decision], None] = lambda d: None,
    sleep: Callable[[float], None] = time.sleep,
) -> Decision:
    """Tick until the rollout is promoted, rolled back, or times out."""
    deadline = time.monotonic() + timeout_s
    while True:
        d = tick(admin, policy)
        on_decision(d)
        if d.action in {"promote", "rollback", "idle"}:
            return d
        if time.monotonic() > deadline:
            admin.rollback("rollout timed out")
            return Decision("rollback", "rollout timed out")
        sleep(interval_s)
