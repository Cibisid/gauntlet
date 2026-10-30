"""Releases: immutable, content-addressed bundles of behaviour (ADR-0004)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

REQUIRED_KEYS = ("app", "prompt", "model", "params")
# Keys that look like inline credentials. "max_tokens" must stay allowed, so
# token-like keys only match when they name an actual credential.
SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|password|passwd|private[_-]?key|"
    r"(access|auth|bearer|refresh|session)[_-]?token)",
    re.IGNORECASE,
)


class ReleaseError(ValueError):
    """Raised when a release document is invalid."""


def _check_no_secrets(obj: Any, path: str = "") -> None:
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            lowered = str(key).lower()
            # Allow references such as {"api_key_ref": "secretsmanager:..."}.
            if SECRET_KEY_PATTERN.search(lowered) and not lowered.endswith("_ref"):
                raise ReleaseError(f"inline secret-like key not allowed: {path}{key}")
            _check_no_secrets(value, f"{path}{key}.")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _check_no_secrets(item, f"{path}[{i}].")


def validate(doc: Mapping[str, Any]) -> None:
    """Validate a release document. Raises ReleaseError."""
    missing = [k for k in REQUIRED_KEYS if k not in doc]
    if missing:
        raise ReleaseError(f"missing required keys: {missing}")
    _check_no_secrets(doc)


def canonical_json(doc: Mapping[str, Any]) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 safe."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def release_id(doc: Mapping[str, Any]) -> str:
    """Content address of a release: 'rel_' + first 16 hex chars of SHA-256."""
    validate(doc)
    digest = hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()
    return f"rel_{digest[:16]}"
