"""Spawns the real stdio server. Each test starts a process, so keep this file small."""

import json

from rootsignal_agent.agent.guardrails import ALLOWED_TOOLS
from rootsignal_agent.mcp_server.client import platform_session
from rootsignal_agent.sim.engine import load_scenarios


async def test_lists_exactly_the_six_read_only_tools():
    async with platform_session("oom_01") as session:
        tools = (await session.list_tools()).tools
    assert {t.name for t in tools} == ALLOWED_TOOLS
    for tool in tools:
        assert tool.description
        assert tool.input_schema["type"] == "object"


async def test_redaction_end_to_end():
    job = load_scenarios()["auth_expired_01"].job_name
    async with platform_session("auth_expired_01") as session:
        result = await session.call_tool("search_logs", {"job_name": job, "limit": 100})
    assert not result.is_error
    text = result.content[0].text
    assert "[REDACTED]" in text  # something was actually redacted
    assert "FAKE-" not in text


async def test_error_result_then_session_still_works():
    job = load_scenarios()["oom_01"].job_name
    async with platform_session("oom_01") as session:
        bad = await session.call_tool("get_job_status", {"job_name": "nope"})
        assert bad.is_error
        assert job in bad.content[0].text  # message tells the caller the valid job
        good = await session.call_tool("get_job_status", {"job_name": job})
    assert not good.is_error


async def test_propose_remediation_dry_run_and_allowlist():
    job = load_scenarios()["oom_01"].job_name
    async with platform_session("oom_01") as session:
        bad = await session.call_tool(
            "propose_remediation", {"action": "delete_job", "job_name": job, "reason": "x"}
        )
        assert bad.is_error
        ok = await session.call_tool(
            "propose_remediation", {"action": "increase_memory", "job_name": job, "reason": "OOM"}
        )
    assert not ok.is_error
    assert json.loads(ok.content[0].text)["executed"] is False
