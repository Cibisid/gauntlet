"""Render a release's prompt templates for a case.

Templates use ``string.Template`` (``$name``) rather than ``str.format`` so that
user-controlled values containing braces cannot inject format directives.
Non-string inputs are serialised as JSON.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from string import Template
from typing import Any


class PromptError(ValueError):
    """Raised when a template cannot be rendered."""


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def render_messages(prompt: Mapping[str, Any], inputs: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return OpenAI-style chat messages for one case."""
    if "user_template" not in prompt:
        raise PromptError("release prompt needs a 'user_template'")
    values = {k: _as_text(v) for k, v in inputs.items()}
    try:
        user = Template(str(prompt["user_template"])).substitute(values)
    except KeyError as exc:
        raise PromptError(f"template variable {exc} missing from case inputs") from exc
    except ValueError as exc:
        raise PromptError(f"invalid template: {exc}") from exc
    messages: list[dict[str, str]] = []
    if prompt.get("system"):
        messages.append({"role": "system", "content": str(prompt["system"])})
    messages.append({"role": "user", "content": user})
    return messages
