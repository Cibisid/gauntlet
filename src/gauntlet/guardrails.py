"""Input and output guardrails.

Input checks flag likely prompt injection and enforce size limits. Output checks
block protected-string leaks (system prompt, canaries) and redact PII before
anything is returned or stored. Policies are part of a Release (ADR-0004), so a
guardrail change goes through the same gate as a prompt or model change.

The injection detector is a transparent pattern baseline, not a classifier. Its
precision/recall is measured by ``evaluate_detector`` and reported, never assumed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_instructions": re.compile(
        r"\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(instruction|rule|guideline|constraint|prompt)s?\b",
        re.I,
    ),
    "reveal_system": re.compile(
        r"\b(reveal|print|repeat|disclose|output|show)\b[^.\n]{0,40}"
        r"\b(system prompt|instructions|configuration|reference code|internal code|hidden)\b",
        re.I,
    ),
    "override_mode": re.compile(
        r"\b(system override|debug mode|developer mode|admin request)\b", re.I
    ),
    "role_hijack": re.compile(r"\byou are now\b|\bact as (an? )?(unrestricted|jailbroken)\b", re.I),
}

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone": re.compile(r"(?<!\d)(?:\+1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)"),
    "card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
}

BLOCKED_OUTPUT = "I can't share that. Please ask about trial eligibility."


def _luhn_ok(digits: str) -> bool:
    nums = [int(d) for d in digits if d.isdigit()]
    if not 13 <= len(nums) <= 16:
        return False
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def detect_injection(text: str) -> list[str]:
    """Names of injection patterns found in ``text`` (empty list if none)."""
    return [name for name, pat in INJECTION_PATTERNS.items() if pat.search(text)]


def redact_pii(text: str) -> tuple[str, dict[str, int]]:
    """Replace PII with ``[REDACTED:<type>]``; return the new text and counts per type."""
    counts: dict[str, int] = {}

    for kind, pat in PII_PATTERNS.items():

        def _sub(m: re.Match[str], kind: str = kind) -> str:
            if kind == "card" and not _luhn_ok(m.group(0)):
                return m.group(0)
            counts[kind] = counts.get(kind, 0) + 1
            return f"[REDACTED:{kind}]"

        text = pat.sub(_sub, text)
    return text, counts


@dataclass(frozen=True)
class GuardrailPolicy:
    max_input_chars: int = 20_000
    block_on_injection: bool = False
    redact_output_pii: bool = True
    protected_strings: tuple[str, ...] = ()

    @classmethod
    def from_release(cls, release: Mapping[str, Any]) -> GuardrailPolicy | None:
        """Build the policy from a release's optional ``guardrails`` section."""
        raw = release.get("guardrails")
        if not raw:
            return None
        return cls(
            max_input_chars=int(raw.get("max_input_chars", 20_000)),
            block_on_injection=bool(raw.get("block_on_injection", False)),
            redact_output_pii=bool(raw.get("redact_output_pii", True)),
            protected_strings=tuple(str(s) for s in raw.get("protected_strings", ())),
        )


@dataclass(frozen=True)
class Verdict:
    blocked: bool
    text: str
    reasons: tuple[str, ...] = field(default_factory=tuple)


def check_input(messages: Sequence[Mapping[str, str]], policy: GuardrailPolicy) -> Verdict:
    """Inspect user-controlled content (all non-system messages)."""
    user_text = "\n".join(m.get("content", "") for m in messages if m.get("role") != "system")
    reasons: list[str] = []
    if len(user_text) > policy.max_input_chars:
        return Verdict(True, "", ("input_too_large",))
    hits = detect_injection(user_text)
    if hits:
        reasons.append("prompt_injection")
    blocked = bool(hits) and policy.block_on_injection
    return Verdict(blocked, user_text, tuple(reasons))


def check_output(text: str, policy: GuardrailPolicy) -> Verdict:
    """Block protected-string leaks; redact PII. Returns the text safe to return."""
    lowered = text.lower()
    if any(s and s.lower() in lowered for s in policy.protected_strings):
        return Verdict(True, BLOCKED_OUTPUT, ("canary_leak",))
    if policy.redact_output_pii:
        redacted, counts = redact_pii(text)
        if counts:
            return Verdict(False, redacted, ("pii_output",))
    return Verdict(False, text, ())


@dataclass(frozen=True)
class DetectorReport:
    true_pos: int
    false_pos: int
    false_neg: int
    true_neg: int

    @property
    def precision(self) -> float:
        d = self.true_pos + self.false_pos
        return self.true_pos / d if d else float("nan")

    @property
    def recall(self) -> float:
        d = self.true_pos + self.false_neg
        return self.true_pos / d if d else float("nan")


def evaluate_detector(attacks: Iterable[str], benign: Iterable[str]) -> DetectorReport:
    """Confusion counts of ``detect_injection`` on labelled attack and benign texts."""
    tp = fn = fp = tn = 0
    for t in attacks:
        if detect_injection(t):
            tp += 1
        else:
            fn += 1
    for t in benign:
        if detect_injection(t):
            fp += 1
        else:
            tn += 1
    return DetectorReport(tp, fp, fn, tn)
