"""Manual smoke test: python -m rootsignal_agent.mcp_server.smoke --scenario oom_01"""

import argparse
import asyncio

from rootsignal_agent.mcp_server.client import platform_session
from rootsignal_agent.sim.engine import load_scenarios


async def main(scenario: str) -> None:
    spec = load_scenarios()[scenario]
    job, team = spec.job_name, spec.team
    calls = [
        ("get_job_status", {"job_name": job}),
        ("search_logs", {"job_name": job, "level": "ERROR", "limit": 5}),
        ("query_metric", {"metric": "executor_memory_utilization", "job_name": job}),
        ("search_runbooks", {"query": spec.user_report}),
        ("list_recent_incidents", {"team": team}),
        (
            "propose_remediation",
            {"action": "escalate_to_oncall", "job_name": job, "reason": "smoke"},
        ),
    ]
    async with platform_session(scenario) as session:
        tools = (await session.list_tools()).tools
        print("tools:", ", ".join(t.name for t in tools))
        for name, args in calls:
            result = await session.call_tool(name, args)
            text = result.content[0].text
            print(f"\n{name}{args}\n  isError={result.is_error} {text[:200]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    asyncio.run(main(parser.parse_args().scenario))
