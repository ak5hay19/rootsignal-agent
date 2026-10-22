"""Demo CLI: python -m rootsignal_agent.sim --list | --scenario <id>

Prints only what an agent could observe. Ground truth is never shown.
"""

from __future__ import annotations

import argparse

from rootsignal_agent.sim.engine import PlatformEngine, load_scenarios
from rootsignal_agent.sim.metrics import METRIC_CATALOG


def list_scenarios() -> None:
    for s in load_scenarios().values():
        print(f"{s.id:<24} {s.team:<18} {s.job_name:<24} {s.user_report[:70]}...")


def show_scenario(scenario_id: str) -> None:
    engine = PlatformEngine.from_dir(active=scenario_id)
    job = load_scenarios()[scenario_id].job_name
    print(f"=== User report ===\n{engine.user_report()}\n")
    print("=== Job status ===")
    for key, value in engine.get_job_status(job).items():
        print(f"  {key}: {value}")
    print("\n=== Last 15 log lines ===")
    for line in engine.get_logs(job, limit=15):
        print(f"  {line['ts']} {line['level']:<5} [{line['component']}] {line['message']}")
    print("\n=== Metrics (last 6h) ===")
    for name in METRIC_CATALOG:
        m = engine.get_metric(name, job, window_minutes=360)
        print(
            f"  {name:<30} min={m['min']:<12} max={m['max']:<12} last={m['last']:<12} {m['unit']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m rootsignal_agent.sim")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="list all scenarios")
    group.add_argument("--scenario", metavar="ID", help="show what the agent could see")
    args = parser.parse_args()
    if args.list:
        list_scenarios()
    else:
        show_scenario(args.scenario)


if __name__ == "__main__":
    main()
