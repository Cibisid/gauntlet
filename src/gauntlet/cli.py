"""Command-line interface. Run ``gauntlet <command> --help`` for details.

Offline evaluation:  id, run, gate, label, qualify, agreement, guardrail-eval
Production:          proxy, hash-key, rollout, audit-verify, drift, triage, bench
Testing:             mock-server

Secrets are read from the environment, never from flags:
GAUNTLET_API_KEY (provider or proxy client key), GAUNTLET_ADMIN_KEY (proxy admin).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from gauntlet import __version__
from gauntlet.cases import case_set_hash, load_cases, select, write_cases
from gauntlet.gate import GateInputError, evaluate_gate
from gauntlet.providers import OpenAICompatibleProvider
from gauntlet.release import load_release, release_id
from gauntlet.runner import read_results, run_release, write_results


def _cmd_id(args: argparse.Namespace) -> int:
    print(release_id(load_release(args.release)))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from gauntlet.judges import Judge, JudgeError, Rubric, require_qualified

    release = load_release(args.release)
    cases = load_cases(args.cases)
    provider = OpenAICompatibleProvider(
        args.base_url,
        timeout_s=args.timeout,
        max_retries=args.max_retries,
        max_rpm=args.max_rpm,
    )
    judge = None
    if args.judge_rubric:
        rubric = Rubric.load(args.judge_rubric)
        if not args.allow_unqualified_judge:
            try:
                require_qualified(rubric, args.qualifications)
            except JudgeError as exc:
                print(f"refusing to gate with judge: {exc}", file=sys.stderr)
                return 2
        judge = Judge(rubric, OpenAICompatibleProvider(args.judge_base_url or args.base_url))
    rid = release_id(release)
    if args.gate_cases_only:
        cases = [c for c in cases if c.suite == "security" or c.split == "holdout"]
    kept = []
    if args.resume and Path(args.out).exists():
        # Keep successful results for this exact release; errored cases run again.
        kept = [r for r in read_results(args.out) if r.release_id == rid and not r.error]
    done = {r.case_id for r in kept}
    todo = [c for c in cases if c.id not in done]
    if args.limit is not None:
        todo = todo[: args.limit]
    try:
        new = run_release(release, todo, provider, concurrency=args.concurrency, judge=judge)
    finally:
        provider.close()
    results = kept + new
    write_results(args.out, results)
    errors = sum(1 for r in results if r.error)
    complete = len(results) - errors
    print(
        f"ran {len(new)} cases for {rid} (case set {case_set_hash(cases)[:12]}); "
        f"complete: {complete}/{len(cases)}; errors: {errors}; wrote {args.out}"
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


def _cmd_label(args: argparse.Namespace) -> int:
    from gauntlet.labels import label_interactive, sample_for_labeling

    cases = {c.id: c for c in load_cases(args.cases)}
    items = sample_for_labeling(read_results(args.results), n=args.n, seed=args.seed)
    labels = label_interactive(items, cases, labeler=args.labeler, out_path=args.out)
    print(f"recorded {len(labels)} new labels in {args.out}")
    return 0


def _cmd_qualify(args: argparse.Namespace) -> int:
    from gauntlet.judges import Judge, Rubric, describe, qualify
    from gauntlet.labels import load_labels

    rubric = Rubric.load(args.rubric)
    labels = load_labels(args.labels)
    cases = {c.id: c for c in load_cases(args.cases)}
    outputs = {r.case_id: r.output for r in read_results(args.results)}
    judge = Judge(rubric, OpenAICompatibleProvider(args.base_url))
    usable = [lab for lab in labels if lab.case_id in outputs and lab.case_id in cases]
    judge_labels = [
        judge.verdict(cases[lab.case_id].inputs, outputs[lab.case_id], cases[lab.case_id].expected)
        for lab in usable
    ]
    record = qualify(
        rubric, judge_labels, [lab.label for lab in usable], min_labels=args.min_labels
    )
    path = record.save(args.out_dir)
    print(describe(record))
    print(f"wrote {path}")
    return 0 if record.qualified else 1


def _cmd_agreement(args: argparse.Namespace) -> int:
    from gauntlet.labels import agreement, load_labels

    n, kappa = agreement(load_labels(args.a), load_labels(args.b))
    print(f"inter-annotator agreement on {n} shared items: Cohen's kappa = {kappa:.3f}")
    return 0


def _cmd_guardrail_eval(args: argparse.Namespace) -> int:
    from gauntlet.guardrails import evaluate_detector
    from gauntlet.stats import wilson_interval

    cases = load_cases(args.cases)

    def notes(c: object) -> str:
        return str(c.inputs.get("payload", {}).get("patient", {}).get("notes", ""))  # type: ignore[attr-defined]

    attacks = [notes(c) for c in select(cases, suite="security")]
    benign = [notes(c) for c in select(cases, suite="quality")]
    rep = evaluate_detector(attacks, benign)
    r_lo, r_hi = wilson_interval(rep.true_pos, max(1, rep.true_pos + rep.false_neg))
    fp_lo, fp_hi = wilson_interval(rep.false_pos, max(1, rep.false_pos + rep.true_neg))
    print(
        f"injection detector on {len(attacks)} attacks / {len(benign)} benign notes:\n"
        f"  recall {rep.recall:.1%} (95% CI {r_lo:.1%} to {r_hi:.1%})\n"
        f"  false-positive rate {rep.false_pos}/{rep.false_pos + rep.true_neg} "
        f"(95% CI {fp_lo:.1%} to {fp_hi:.1%})\n"
        "  note: on synthetic templates the detector was written against; "
        "expect lower recall on novel attacks."
    )
    return 0


def _cmd_proxy(args: argparse.Namespace) -> int:
    from gauntlet.proxy import serve

    serve(args.host, args.port)
    return 0


def _cmd_hash_key(args: argparse.Namespace) -> int:
    from gauntlet.proxy import hash_key

    key = os.environ.get("GAUNTLET_KEY_TO_HASH") or getpass.getpass("key to hash: ")
    if len(key) < 24:
        print("refusing: use a key of at least 24 characters", file=sys.stderr)
        return 2
    print(hash_key(key))
    return 0


def _admin(args: argparse.Namespace) -> object:
    from gauntlet.rollout import ProxyAdmin

    key = os.environ.get("GAUNTLET_ADMIN_KEY", "")
    if not key:
        raise SystemExit("set GAUNTLET_ADMIN_KEY")
    return ProxyAdmin(args.proxy, key)


def _cmd_rollout(args: argparse.Namespace) -> int:
    from gauntlet import rollout

    admin = _admin(args)
    if not isinstance(admin, rollout.ProxyAdmin):  # pragma: no cover - type narrowing
        raise TypeError("admin client")
    if args.action == "deploy":
        doc = load_release(args.release)
        out = admin.set_routing(stable=doc, canary=None, canary_weight=0.0, reason="deploy")
        print(json.dumps(out["weights"]))
        return 0
    if args.action == "status":
        print(json.dumps(admin.routing()["weights"], indent=2))
        return 0
    if args.action == "rollback":
        admin.rollback(args.reason or "manual rollback")
        print("rolled back")
        return 0
    if args.action == "promote":
        admin.promote()
        print("promoted")
        return 0
    doc = load_release(args.release) if args.release else {}
    policy = rollout.RolloutPolicy.from_release(doc)
    if args.action == "start":
        out = rollout.start(admin, doc, policy)
        print(json.dumps(out["weights"]))
        return 0
    if args.action == "tick":
        d = rollout.tick(admin, policy)
        print(f"{d.action}: {d.reason}")
        return 0
    d = rollout.watch(
        admin, policy, interval_s=args.interval, timeout_s=args.timeout,
        on_decision=lambda d: print(f"{d.action}: {d.reason}", flush=True),
    )  # fmt: skip
    return 0 if d.action == "promote" else 1


def _cmd_audit_verify(args: argparse.Namespace) -> int:
    from gauntlet.proxy import verify_audit_log

    ok, n, msg = verify_audit_log(args.path)
    print(f"{'OK' if ok else 'TAMPERED'}: {n} entries checked ({msg})")
    return 0 if ok else 1


def _cmd_drift(args: argparse.Namespace) -> int:
    from gauntlet.monitor import PSI_ALERT, drift_report, read_jsonl

    report = drift_report(read_jsonl(args.reference), read_jsonl(args.current))
    worst = max(report.values())
    for name, value in report.items():
        flag = "  <-- drift" if value > args.threshold else ""
        print(f"{name:15s} PSI {value:.3f}{flag}")
    _ = PSI_ALERT
    return 1 if worst > args.threshold else 0


def _cmd_triage(args: argparse.Namespace) -> int:
    from gauntlet.monitor import read_jsonl, triage

    cases = triage(read_jsonl(args.traces), read_jsonl(args.feedback))
    write_cases(args.out, cases)
    print(f"wrote {len(cases)} candidate cases needing labels to {args.out}")
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    from gauntlet.bench import bench, dump, proxy_sender, to_markdown

    payloads = [dict(c.inputs) for c in select(load_cases(args.cases), suite="quality")]
    send = proxy_sender(args.url, args.app, os.environ.get("GAUNTLET_API_KEY", ""))
    levels = [int(x) for x in args.levels.split(",")]
    report = bench(send, payloads, levels, args.duration, target=args.url, note=args.note)
    dump(report, args.out)
    print(to_markdown(report))
    return 0


def _cmd_mock(args: argparse.Namespace) -> int:
    from gauntlet.mock_server import serve

    serve(args.host, args.port)
    return 0


def _cmd_summarize(args: argparse.Namespace) -> int:
    from gauntlet.summary import summarize, to_markdown

    rows = {}
    for item in args.run:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            print(f"--run expects NAME=PATH, got {item!r}", file=sys.stderr)
            return 2
        rows[name] = summarize(read_results(path), split=args.split)
    md = to_markdown(rows)
    print(md, end="")
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
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
    s.add_argument("--base-url", required=True, help="OpenAI-compatible base URL")
    s.add_argument("--out", required=True)
    s.add_argument("--concurrency", type=int, default=8)
    s.add_argument("--timeout", type=float, default=60.0)
    s.add_argument("--max-rpm", type=float, help="pace requests to stay under a rate limit")
    s.add_argument("--max-retries", type=int, default=3, help="retries on 429/5xx/timeouts")
    s.add_argument(
        "--gate-cases-only", action="store_true", help="only holdout quality + security cases"
    )
    s.add_argument("--resume", action="store_true", help="keep finished cases already in --out")
    s.add_argument("--limit", type=int, help="run at most this many new cases (daily quotas)")
    s.add_argument("--judge-rubric", help="rubric YAML for cases scored by 'judge:<name>'")
    s.add_argument("--judge-base-url", help="endpoint for the judge model (default: --base-url)")
    s.add_argument("--qualifications", default="judges/qualifications")
    s.add_argument("--allow-unqualified-judge", action="store_true", help="for experiments only")
    s.set_defaults(func=_cmd_run)

    s = sub.add_parser("gate", help="compare candidate results to baseline results")
    s.add_argument("--baseline", required=True)
    s.add_argument("--candidate", required=True)
    s.add_argument("--release", required=True, help="candidate release (gate config, budgets)")
    s.add_argument("--split", default="holdout")
    s.add_argument("--report", help="write the markdown report here")
    s.set_defaults(func=_cmd_gate)

    s = sub.add_parser("label", help="label sampled outputs pass/fail (interactive)")
    s.add_argument("--results", required=True)
    s.add_argument("--cases", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--labeler", required=True)
    s.add_argument("--n", type=int, default=50)
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(func=_cmd_label)

    s = sub.add_parser("qualify", help="measure a judge against human labels")
    s.add_argument("--rubric", required=True)
    s.add_argument("--labels", required=True)
    s.add_argument("--results", required=True)
    s.add_argument("--cases", required=True)
    s.add_argument("--base-url", required=True)
    s.add_argument("--out-dir", default="judges/qualifications")
    s.add_argument("--min-labels", type=int, default=200)
    s.set_defaults(func=_cmd_qualify)

    s = sub.add_parser("agreement", help="Cohen's kappa between two labellers")
    s.add_argument("a")
    s.add_argument("b")
    s.set_defaults(func=_cmd_agreement)

    s = sub.add_parser("guardrail-eval", help="measure the injection detector on a case set")
    s.add_argument("--cases", required=True)
    s.set_defaults(func=_cmd_guardrail_eval)

    s = sub.add_parser("proxy", help="run the data-plane proxy (config from GAUNTLET_* env)")
    s.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 inside containers")
    s.add_argument("--port", type=int, default=8080)
    s.set_defaults(func=_cmd_proxy)

    s = sub.add_parser("hash-key", help="scrypt-hash an API/admin key for proxy config")
    s.set_defaults(func=_cmd_hash_key)

    s = sub.add_parser("rollout", help="deploy, canary, promote or roll back via the proxy")
    s.add_argument(
        "action", choices=["deploy", "start", "tick", "watch", "rollback", "promote", "status"]
    )
    s.add_argument("--proxy", required=True, help="proxy base URL, e.g. http://localhost:8080")
    s.add_argument("--release", help="release YAML (deploy/start/tick/watch)")
    s.add_argument("--reason", default="")
    s.add_argument("--interval", type=float, default=10.0)
    s.add_argument("--timeout", type=float, default=3600.0)
    s.set_defaults(func=_cmd_rollout)

    s = sub.add_parser("audit-verify", help="verify the audit log hash chain")
    s.add_argument("path")
    s.set_defaults(func=_cmd_audit_verify)

    s = sub.add_parser("drift", help="PSI drift between two trace files")
    s.add_argument("--reference", required=True)
    s.add_argument("--current", required=True)
    s.add_argument("--threshold", type=float, default=0.25)
    s.set_defaults(func=_cmd_drift)

    s = sub.add_parser("triage", help="flagged traces -> candidate cases needing labels")
    s.add_argument("--traces", required=True)
    s.add_argument("--feedback", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(func=_cmd_triage)

    s = sub.add_parser("bench", help="load-test the proxy")
    s.add_argument("--url", required=True)
    s.add_argument("--app", default="trialbridge")
    s.add_argument("--cases", required=True)
    s.add_argument("--levels", default="1,8,32")
    s.add_argument("--duration", type=float, default=10.0)
    s.add_argument("--out", default="bench.json")
    s.add_argument("--note", default="")
    s.set_defaults(func=_cmd_bench)

    s = sub.add_parser("summarize", help="per-release results table from run outputs")
    s.add_argument("--run", action="append", required=True, help="NAME=results.jsonl")
    s.add_argument("--split", default="holdout")
    s.add_argument("--out", help="write markdown here")
    s.add_argument("--json", help="write raw numbers here")
    s.set_defaults(func=_cmd_summarize)

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
