"""Command-line interface.

gauntlet id RELEASE.yaml
gauntlet run --release R.yaml --cases C.jsonl --base-url URL --out results.jsonl
gauntlet gate --baseline B.jsonl --candidate C.jsonl --release R.yaml [--report out.md]
gauntlet mock-server [--port 8089]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from gauntlet import __version__
from gauntlet.cases import case_set_hash, load_cases
from gauntlet.gate import GateInputError, evaluate_gate
from gauntlet.providers import OpenAICompatibleProvider
from gauntlet.release import load_release, release_id
from gauntlet.runner import read_results, run_release, write_results


def _cmd_id(args: argparse.Namespace) -> int:
    print(release_id(load_release(args.release)))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    release = load_release(args.release)
    cases = load_cases(args.cases)
    provider = OpenAICompatibleProvider(args.base_url, timeout_s=args.timeout)
    try:
        results = run_release(release, cases, provider, concurrency=args.concurrency)
    finally:
        provider.close()
    write_results(args.out, results)
    errors = sum(1 for r in results if r.error)
    print(
        f"ran {len(results)} cases for {release_id(release)} "
        f"(case set {case_set_hash(cases)[:12]}); errors: {errors}; wrote {args.out}"
    )
    return 0


def _cmd_gate(args: argparse.Namespace) -> int:
    release = load_release(args.release)
    try:
        report = evaluate_gate(
            read_results(args.baseline),
            read_results(args.candidate),
            gate_config=release.get("gate"),
            budgets=release.get("budgets"),
            split=args.split,
        )
    except GateInputError as exc:
        print(f"gate input error: {exc}", file=sys.stderr)
        return 2
    markdown = report.to_markdown()
    print(markdown)
    if args.report:
        Path(args.report).write_text(markdown, encoding="utf-8")
    return 0 if report.passed else 1


def _cmd_mock(args: argparse.Namespace) -> int:
    from gauntlet.mock_server import serve

    serve(args.host, args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gauntlet", description="Eval-gated releases for LLM systems")
    p.add_argument("--version", action="version", version=f"gauntlet {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("id", help="print a release's content-addressed ID")
    s.add_argument("release")
    s.set_defaults(func=_cmd_id)

    s = sub.add_parser("run", help="run a release over a case set")
    s.add_argument("--release", required=True)
    s.add_argument("--cases", required=True)
    s.add_argument(
        "--base-url",
        required=True,
        help="OpenAI-compatible base URL, e.g. http://localhost:8089/v1",
    )
    s.add_argument("--out", required=True)
    s.add_argument("--concurrency", type=int, default=8)
    s.add_argument("--timeout", type=float, default=60.0)
    s.set_defaults(func=_cmd_run)

    s = sub.add_parser("gate", help="compare candidate results to baseline results")
    s.add_argument("--baseline", required=True)
    s.add_argument("--candidate", required=True)
    s.add_argument(
        "--release", required=True, help="candidate release (for gate config and budgets)"
    )
    s.add_argument("--split", default="holdout")
    s.add_argument("--report", help="write the markdown report here")
    s.set_defaults(func=_cmd_gate)

    s = sub.add_parser("mock-server", help="run the deterministic mock LLM server")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8089)
    s.set_defaults(func=_cmd_mock)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
