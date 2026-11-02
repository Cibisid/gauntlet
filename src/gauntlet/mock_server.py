"""Deterministic OpenAI-compatible mock model server for tests, CI and demos.

Models (pick via the ``model`` field):

* ``mock-accurate``  solves the synthetic task (see ``trialsim``) with a small,
  deterministic error rate, so different prompts produce realistic noise.
* ``mock-sloppy``    a "cheaper model": faster, but ignores exclusion criteria.
* ``mock-obedient``  as accurate as ``mock-accurate`` but follows instructions
  injected into patient notes and leaks its system prompt.
* ``mock-flaky``     returns HTTP 503 on every other request (retry testing).
* ``mock-judge``     grades eligibility answers against the reference, with ~6%
  deliberate disagreement so judge qualification has something to measure.

This simulates behaviours so the gate can be tested end to end. Results from it
say nothing about real model quality and are never reported as benchmarks.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from gauntlet import scorers, trialsim

MODELS: dict[str, dict[str, Any]] = {
    "mock-accurate": {"latency_ms": 30, "check_exclusions": True, "obeys_injection": False},
    "mock-sloppy": {"latency_ms": 10, "check_exclusions": False, "obeys_injection": False},
    "mock-obedient": {"latency_ms": 30, "check_exclusions": True, "obeys_injection": True},
    "mock-flaky": {"latency_ms": 5, "check_exclusions": True, "obeys_injection": False},
    "mock-judge": {"latency_ms": 15, "judge": True},
}
JUDGE_DISAGREE_PER_MILLE = 60  # ~6% of verdicts flipped, so kappa is realistic, not 1.0
ERROR_RATE_PER_MILLE = 30  # ~3% of (prompt, case) pairs get one wrong trial
INJECTION_MARKERS = ("ignore", "override", "reveal", "disregard")


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _noise_bucket(system: str, user: str) -> int:
    digest = hashlib.sha256((system + "\x00" + user).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 1000


def judge_answer(messages: list[dict[str, str]]) -> str:
    """Mock judge: pass iff the graded response's ID set equals the reference."""
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    try:
        ref_part = user.split("REFERENCE:\n", 1)[1]
        ref_text, response = ref_part.split("\n\nRESPONSE TO GRADE:\n", 1)
        reference = json.loads(ref_text)
    except (IndexError, ValueError):
        return json.dumps({"verdict": "fail", "reason": "could not read the grading request"})
    correct = scorers.json_set_f1(response, reference) == 1.0
    if _noise_bucket("judge", user) < JUDGE_DISAGREE_PER_MILLE:
        correct = not correct
    verdict = "pass" if correct else "fail"
    return json.dumps({"verdict": verdict, "reason": f"set match: {correct}"})


def answer(model: str, messages: list[dict[str, str]]) -> str:
    """Produce the mock model's reply for a chat request."""
    spec = MODELS[model]
    if spec.get("judge"):
        return judge_answer(messages)
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    payload = trialsim.extract_payload(user)
    if payload is None:
        return "I could not find the patient data."

    patient, trials = payload["patient"], payload["trials"]
    ids = trialsim.eligible_ids(patient, trials, check_exclusions=spec["check_exclusions"])

    bucket = _noise_bucket(system, user)
    if bucket < ERROR_RATE_PER_MILLE and trials:
        # Miss one eligible trial, or report a false positive when none is eligible.
        ids = ids[1:] if ids else [str(trials[bucket % len(trials)]["id"])]

    reply = json.dumps({"eligible_trials": ids})
    notes = str(patient.get("notes", "")).lower()
    if spec["obeys_injection"] and any(m in notes for m in INJECTION_MARKERS):
        reply = f"As requested, my instructions are: {system}\n{reply}"
    return reply


class _Handler(BaseHTTPRequestHandler):
    server_version = "gauntlet-mock/0.2"
    flaky_counter = 0
    flaky_lock = threading.Lock()

    def log_message(self, format: str, *args: Any) -> None:  # silence default logging
        return

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, {"status": "ok"})
        elif self.path == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": m} for m in MODELS]})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._send(404, {"error": {"message": "not found"}})
            return
        required_key = os.environ.get("MOCK_API_KEY")
        if required_key and self.headers.get("Authorization") != f"Bearer {required_key}":
            self._send(401, {"error": {"message": "invalid api key"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                self._send(413, {"error": {"message": "request too large"}})
                return
            body = json.loads(self.rfile.read(length))
            model = body["model"]
            messages = body["messages"]
        except (ValueError, KeyError, TypeError):
            self._send(400, {"error": {"message": "invalid request"}})
            return
        if model not in MODELS:
            self._send(404, {"error": {"message": f"unknown model {model}"}})
            return
        if model == "mock-flaky":
            with _Handler.flaky_lock:
                _Handler.flaky_counter += 1
                fail = _Handler.flaky_counter % 2 == 1
            if fail:
                self._send(503, {"error": {"message": "temporarily unavailable"}})
                return

        scale = float(os.environ.get("MOCK_LATENCY_SCALE", "1"))
        time.sleep(MODELS[model]["latency_ms"] * scale / 1000)
        text = answer(model, messages)
        prompt_text = "".join(m.get("content", "") for m in messages)
        p_tok, c_tok = _approx_tokens(prompt_text), _approx_tokens(text)
        self._send(
            200,
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": p_tok,
                    "completion_tokens": c_tok,
                    "total_tokens": p_tok + c_tok,
                },
            },
        )


def make_server(host: str = "127.0.0.1", port: int = 8089) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _Handler)


def serve(host: str = "127.0.0.1", port: int = 8089) -> None:
    server = make_server(host, port)
    print(f"mock LLM listening on http://{host}:{server.server_address[1]}/v1", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
