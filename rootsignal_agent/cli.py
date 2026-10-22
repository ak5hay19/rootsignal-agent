"""Command line entry point.

    python -m rootsignal_agent.cli --scenario oom_01 ["optional report text"]
    python -m rootsignal_agent.cli --all

This is the only module that loads .env; library code reads plain environment variables.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from rootsignal_agent.agent.guardrails import DEFAULT_MAX_TOOL_CALLS
from rootsignal_agent.agent.loop import DEFAULT_MAX_TOKENS, Investigator, MissingApiKeyError
from rootsignal_agent.agent.models import InvestigationResult
from rootsignal_agent.agent.pricing import PRICING, estimate_cost_usd
from rootsignal_agent.agent.prompts import SYSTEM_PROMPTS
from rootsignal_agent.sim.engine import SCENARIO_ENV_VAR, PlatformEngine, load_scenarios

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_PREVIEW_CHARS = 160
DEFAULT_MAX_COST_USD = 0.25


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m rootsignal_agent.cli",
        description="Investigate a simulated platform incident with the RootSignal agent.",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--scenario", help="scenario id to serve, e.g. oom_01")
    target.add_argument("--all", action="store_true", help="run every scenario in turn")
    parser.add_argument(
        "report", nargs="?", help="the user's report (default: the scenario's own report)"
    )
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--verbose", action="store_true", help="print tool calls as they happen")
    parser.add_argument("--model", help="Claude model id (default: $ROOTSIGNAL_AGENT_MODEL)")
    parser.add_argument("--max-tool-calls", type=int, default=DEFAULT_MAX_TOOL_CALLS)
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="max output tokens per model call, including thinking (default: %(default)s)",
    )
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        default=DEFAULT_MAX_COST_USD,
        help="--all stops before the next scenario once the estimated cost reaches this "
        "(default: %(default)s)",
    )
    parser.add_argument("--variant", default="default", choices=sorted(SYSTEM_PROMPTS))
    args = parser.parse_args(argv)
    if args.all and args.report:
        parser.error("--all uses each scenario's own report; do not pass report text")
    if not args.all and not args.scenario:
        # Without --scenario the server falls back to the env var, and the user must say
        # what went wrong since there is no scenario report to borrow.
        if not os.environ.get(SCENARIO_ENV_VAR):
            parser.error(f"pass --scenario, --all, or set {SCENARIO_ENV_VAR}")
        if not args.report:
            parser.error("pass the report text when no --scenario is given")
    return args


# ---- printing --------------------------------------------------------------------------


def print_event(record: dict[str, Any]) -> None:
    """--verbose: one line per tool call and per result. Records are already redacted."""
    if record["event"] == "tool_call":
        print(f"  -> {record['name']}({json.dumps(record['arguments'])})", flush=True)
    elif record["event"] == "tool_result":
        content = record["content"].replace("\n", " ")
        preview = content[:RESULT_PREVIEW_CHARS]
        if len(content) > RESULT_PREVIEW_CHARS:
            preview += "..."
        flag = " ERROR" if record["is_error"] else ""
        redactions = content.count("[REDACTED]")
        note = f" [{redactions} value(s) shown as [REDACTED]]" if redactions else ""
        print(f"  <- {record['name']}{flag} {record['duration_ms']}ms{note}: {preview}")
    elif record["event"] == "forced_submit":
        print(f"  !! forcing submit_report ({record['reason']})")
    elif record["event"] == "truncated_response":
        print(f"  !! model output hit max_tokens ({record['max_tokens']}); stopping")
    elif record["event"] == "forced_tool_choice_rejected":
        print("  !! model rejected forced tool_choice; asked for submit_report in text instead")


def result_cost_usd(model: str, result: InvestigationResult) -> float | None:
    return estimate_cost_usd(model, result.input_tokens, result.output_tokens)


def format_cost(cost: float | None) -> str:
    return f"${cost:.4f} (estimate)" if cost is not None else "unknown (no pricing for model)"


def format_report(result: InvestigationResult, model: str) -> str:
    lines: list[str] = []
    report = result.report
    if report is None:
        lines.append(f"No report ({result.stop_reason}).")
        if result.error_message:
            lines.append(f"Error: {result.error_message}")
    else:
        lines += [
            f"Root cause: {report.root_cause_category}  (confidence: {report.confidence})",
            "",
            report.summary,
            "",
            "Evidence:",
        ]
        for item in report.evidence:
            lines.append(f'  - [{item.tool}] "{item.quote}"')
            lines.append(f"      {item.why_it_matters}")
        lines.append("Alternatives considered:")
        for alt in report.alternatives_considered:
            lines.append(f"  - {alt.category}: {alt.why_rejected}")
        lines.append(f"Runbook: {report.runbook or '(none)'}")
        if report.proposed_remediation:
            rem = report.proposed_remediation
            lines.append(f"Proposed remediation: {rem.action} (dry run, nothing was executed)")
            lines.append(f"      {rem.rationale}")
        else:
            lines.append("Proposed remediation: (none)")
    lines += [
        "",
        "-" * 60,
        f"tool calls: {result.tool_calls_used}  stop: {result.stop_reason}  "
        f"time: {result.elapsed_s:.1f}s  tokens: {result.input_tokens} in / "
        f"{result.output_tokens} out",
        f"cost: {format_cost(result_cost_usd(model, result))}",
        f"trace: {result.trace_path}",
    ]
    return "\n".join(lines)


def format_summary_table(rows: list[dict[str, Any]]) -> str:
    headers = [
        "scenario",
        "predicted",
        "conf",
        "runbook",
        "action",
        "tools",
        "secs",
        "tokens",
        "matches ground truth (dev check, not the eval harness)",
    ]
    table = [headers] + [[str(row[h]) for h in headers] for row in rows]
    widths = [max(len(r[i]) for r in table) for i in range(len(headers))]
    out = [
        "  ".join(cell.ljust(w) for cell, w in zip(r, widths, strict=True)).rstrip() for r in table
    ]
    out.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(out)


# ---- running ---------------------------------------------------------------------------


def scenario_report(scenario_id: str) -> str:
    return PlatformEngine.from_dir(active=scenario_id).user_report()


def ground_truth_match(scenario_id: str, result: InvestigationResult) -> str:
    """Category / runbook / action, each Y or N. Called only AFTER the run has finished."""
    truth = PlatformEngine.from_dir(active=scenario_id).get_ground_truth_for_eval()
    report = result.report
    if report is None:
        return "no report"
    action = report.proposed_remediation.action if report.proposed_remediation else None
    checks = [
        report.root_cause_category == truth["root_cause_category"],
        report.runbook == truth["correct_runbook"],
        action == truth["correct_remediation"],
    ]
    return (
        "/".join("Y" if ok else "N" for ok in checks) + f"  (truth: {truth['root_cause_category']})"
    )


async def run_one(investigator: Investigator, args: argparse.Namespace) -> int:
    report_text = args.report or scenario_report(args.scenario)
    result = await investigator.investigate(report_text, scenario_id=args.scenario)
    print(
        result.model_dump_json(indent=2) if args.json else format_report(result, investigator.model)
    )
    return 0 if result.stop_reason == "submitted" else 1


async def run_all(investigator: Investigator, args: argparse.Namespace) -> int:
    scenario_ids = sorted(load_scenarios())
    print(
        f"Note: --all makes real Anthropic API calls ({len(scenario_ids)} investigations, "
        f"model {investigator.model}).\n"
    )
    rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    total_cost = 0.0  # running estimate; stays 0 if the model has no pricing entry
    skipped: list[str] = []
    for i, sid in enumerate(scenario_ids, 1):
        # Spend guard: checked only between scenarios, so one run is never cut short, but
        # the next one is not started once the estimate has reached the limit.
        if total_cost >= args.max_cost_usd:
            skipped = scenario_ids[i - 1 :]
            break
        print(f"=== [{i}/{len(scenario_ids)}] {sid} ===", flush=True)
        # Each investigation spawns its own server for this scenario.
        result = await investigator.investigate(scenario_report(sid), scenario_id=sid)
        if args.json:
            results.append({"scenario": sid, **result.model_dump(mode="json")})
        else:
            print(format_report(result, investigator.model) + "\n")
        total_cost += result_cost_usd(investigator.model, result) or 0.0
        report = result.report
        rem = report.proposed_remediation if report else None
        rows.append(
            {
                "scenario": sid,
                "predicted": report.root_cause_category if report else "-",
                "conf": report.confidence if report else "-",
                "runbook": (report.runbook or "-") if report else "-",
                "action": rem.action if rem else "-",
                "tools": result.tool_calls_used,
                "secs": f"{result.elapsed_s:.1f}",
                "tokens": result.input_tokens + result.output_tokens,
                # Ground truth is read here, after the investigation has finished.
                "matches ground truth (dev check, not the eval harness)": ground_truth_match(
                    sid, result
                ),
                "stop": result.stop_reason,
            }
        )
    if args.json:
        print(json.dumps(results, indent=2))
    print("Summary (match column = category/runbook/action):")
    print(format_summary_table(rows))
    priced = investigator.model in PRICING
    print(f"\nTotal cost: {format_cost(total_cost if priced else None)}")
    if skipped:
        print(
            f"Stopped early: estimated cost ${total_cost:.4f} reached --max-cost-usd "
            f"${args.max_cost_usd:.2f}. Not run ({len(skipped)}): {', '.join(skipped)}"
        )
    all_submitted = all(r["stop"] == "submitted" for r in rows)
    return 0 if all_submitted and not skipped else 1


def main(argv: list[str] | None = None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")  # values are never printed
    args = parse_args(argv)
    try:
        investigator = Investigator(
            model=args.model,
            prompt_variant=args.variant,
            max_tool_calls=args.max_tool_calls,
            max_tokens=args.max_tokens,
            on_event=print_event if args.verbose else None,
        )
    except MissingApiKeyError:
        print(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill in "
            "ANTHROPIC_API_KEY, or export it in your shell.",
            file=sys.stderr,
        )
        return 1
    runner = run_all if args.all else run_one
    return asyncio.run(runner(investigator, args))


if __name__ == "__main__":
    sys.exit(main())
