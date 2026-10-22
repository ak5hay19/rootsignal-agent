"""Agent loop tests with a scripted fake client and a fake MCP session (no API, no key)."""

import asyncio
import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from rootsignal_agent.agent.guardrails import ALLOWED_TOOLS, DEFAULT_MAX_TURNS
from rootsignal_agent.agent.loop import (
    NUDGE_TEXT,
    TOOL_CHOICE_AUTO,
    TOOL_CHOICE_SUBMIT,
    Investigator,
    MissingApiKeyError,
)
from rootsignal_agent.mcp_server.client import platform_session
from rootsignal_agent.sim.engine import load_scenarios
from tests.fakes import (
    VALID_REPORT,
    FakeAnthropic,
    FakeSession,
    response,
    session_factory,
    submit,
    text,
    tool_use,
)

JOB = {"job_name": "daily_orders"}


def make(script, tmp_path, session=None, **kwargs):
    client = FakeAnthropic(script)
    session = session or FakeSession()
    factory = session_factory(session)
    investigator = Investigator(
        client=client, session_factory=factory, trace_dir=tmp_path, **kwargs
    )
    return investigator, client.messages, session


def trace_events(result):
    with open(result.trace_path) as f:
        return [json.loads(line) for line in f]


def last_user_content(call):
    message = call["messages"][-1]
    assert message["role"] == "user"
    return message["content"]


def _api_request():
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


# ---- happy path and budget -------------------------------------------------------------


async def test_happy_path(tmp_path):
    first_call = tool_use("get_job_status", JOB)
    investigator, messages, session = make(
        [
            response(text("Checking the job."), first_call),
            response(tool_use("search_logs", {**JOB, "level": "ERROR"})),
            response(text("Done."), submit()),
        ],
        tmp_path=tmp_path,
    )
    result = await investigator.investigate("my job failed", scenario_id="oom_01")

    assert result.stop_reason == "submitted"
    assert result.report.root_cause_category == "oom"
    assert result.tool_calls_used == 2
    assert result.turns == 3
    assert (result.input_tokens, result.output_tokens) == (300, 60)
    assert [name for name, _ in session.calls] == ["get_job_status", "search_logs"]

    first = messages.calls[0]
    assert (
        "<user_report>\nmy job failed\n</user_report>" in first["messages"][0]["content"][0]["text"]
    )
    assert {t["name"] for t in first["tools"]} == ALLOWED_TOOLS | {"submit_report"}
    assert all(call["tool_choice"] == TOOL_CHOICE_AUTO for call in messages.calls)
    assert "temperature" not in first
    # The assistant turn is sent back as explicit params, not SDK objects.
    assert messages.calls[1]["messages"][1] == {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Checking the job."},
            {
                "type": "tool_use",
                "id": first_call.id,
                "name": "get_job_status",
                "input": JOB,
            },
        ],
    }

    events = [e["event"] for e in trace_events(result)]
    assert events[0] == "run_start" and events[-1] == "final"
    for expected in ("model_response", "tool_call", "tool_result"):
        assert expected in events
    assert "oom_01" in result.trace_path


async def test_budget_exhaustion_forces_submit(tmp_path):
    investigator, messages, session = make(
        [
            response(tool_use("get_job_status", JOB)),
            # Two requests in one turn: the second one is over the budget of 2.
            response(tool_use("search_logs", JOB), tool_use("query_metric", JOB)),
            response(submit()),
        ],
        tmp_path=tmp_path,
        max_tool_calls=2,
    )
    result = await investigator.investigate("job failed")

    assert len(session.calls) == 2
    over_budget = last_user_content(messages.calls[2])[1]
    assert over_budget["is_error"] is True
    assert "tool budget exhausted" in over_budget["content"]
    assert messages.calls[1]["tool_choice"] == TOOL_CHOICE_AUTO
    assert messages.calls[2]["tool_choice"] == TOOL_CHOICE_SUBMIT
    # The forcing is also said in words, after the tool results.
    assert "used all of your tool calls" in last_user_content(messages.calls[2])[-1]["text"]
    assert result.stop_reason == "budget_exhausted"
    assert result.report is not None
    assert result.tool_calls_used == 2
    assert "forced_submit" in [e["event"] for e in trace_events(result)]


async def test_forced_tool_choice_rejected_falls_back_to_auto(tmp_path):
    rejected = anthropic.BadRequestError(
        'tool_choice: type "tool" and "any" are not supported for this model.',
        response=httpx2.Response(400, request=_api_request()),
        body=None,
    )
    investigator, messages, _ = make(
        [response(tool_use("get_job_status", JOB)), rejected, response(submit())],
        tmp_path=tmp_path,
        max_tool_calls=1,
    )
    result = await investigator.investigate("job failed")

    assert [c["tool_choice"] for c in messages.calls] == [
        TOOL_CHOICE_AUTO,
        TOOL_CHOICE_SUBMIT,
        TOOL_CHOICE_AUTO,
    ]
    assert result.stop_reason == "budget_exhausted"
    assert "forced_tool_choice_rejected" in [e["event"] for e in trace_events(result)]


# ---- tool errors ----------------------------------------------------------------------


async def test_disallowed_tool_never_reaches_session(tmp_path):
    investigator, messages, session = make(
        [response(tool_use("delete_cluster", JOB)), response(submit())], tmp_path=tmp_path
    )
    result = await investigator.investigate("job failed")

    assert session.calls == []
    tool_result = last_user_content(messages.calls[1])[0]
    assert tool_result["is_error"] is True
    assert "tool not allowed" in tool_result["content"]
    assert result.stop_reason == "submitted"
    assert result.tool_calls_used == 0


async def test_session_error_passed_to_model(tmp_path):
    session = FakeSession(results={"get_job_status": ("Unknown job 'x'", True)})
    investigator, messages, _ = make(
        [response(tool_use("get_job_status", {"job_name": "x"})), response(submit())],
        session=session,
        tmp_path=tmp_path,
    )
    result = await investigator.investigate("job failed")

    tool_result = last_user_content(messages.calls[1])[0]
    assert tool_result["is_error"] is True
    assert tool_result["content"] == "Unknown job 'x'"
    assert result.stop_reason == "submitted"
    assert result.tool_calls_used == 1  # errors count against the budget


async def test_tool_timeout(tmp_path):
    investigator, messages, _ = make(
        [response(tool_use("search_logs", JOB)), response(submit())],
        session=FakeSession(delay_s=1.0),
        tmp_path=tmp_path,
        tool_timeout_s=0.05,
    )
    result = await investigator.investigate("job failed")

    tool_result = last_user_content(messages.calls[1])[0]
    assert tool_result["is_error"] is True
    assert "timed out" in tool_result["content"]
    assert result.stop_reason == "submitted"
    assert result.tool_calls_used == 1


# ---- submissions and nudges ------------------------------------------------------------


async def test_invalid_then_valid_submit(tmp_path):
    bad = {**VALID_REPORT, "evidence": []}
    investigator, messages, _ = make([response(submit(bad)), response(submit())], tmp_path=tmp_path)
    result = await investigator.investigate("job failed")

    tool_result = last_user_content(messages.calls[1])[0]
    assert tool_result["is_error"] is True
    assert "evidence" in tool_result["content"]  # the pydantic error text
    assert result.stop_reason == "submitted"
    assert "report_validation_error" in [e["event"] for e in trace_events(result)]


async def test_two_invalid_submits_is_error(tmp_path):
    bad = {**VALID_REPORT, "confidence": "certain"}
    investigator, _, _ = make([response(submit(bad)), response(submit(bad))], tmp_path=tmp_path)
    result = await investigator.investigate("job failed")

    assert result.stop_reason == "error"
    assert result.report is None


async def test_text_only_turn_gets_one_nudge(tmp_path):
    investigator, messages, _ = make(
        [response(text("I think it is OOM.")), response(submit())], tmp_path=tmp_path
    )
    result = await investigator.investigate("job failed")

    assert last_user_content(messages.calls[1]) == [{"type": "text", "text": NUDGE_TEXT}]
    assert messages.calls[1]["tool_choice"] == TOOL_CHOICE_AUTO
    assert result.stop_reason == "submitted"


async def test_two_nudges_then_forced_submit(tmp_path):
    investigator, messages, _ = make(
        [response(text("Hmm.")), response(text("Still thinking.")), response(submit())],
        tmp_path=tmp_path,
    )
    result = await investigator.investigate("job failed")

    assert [c["tool_choice"] for c in messages.calls] == [
        TOOL_CHOICE_AUTO,
        TOOL_CHOICE_AUTO,
        TOOL_CHOICE_SUBMIT,
    ]
    assert result.stop_reason == "submitted"  # forced by nudges, not by the budget


async def test_model_that_never_submits_hits_max_turns(tmp_path):
    script = [response(text("no")) for _ in range(DEFAULT_MAX_TURNS)]
    investigator, messages, _ = make(script, tmp_path=tmp_path)
    result = await investigator.investigate("job failed")

    assert result.stop_reason == "max_turns"
    assert result.report is None
    assert len(messages.calls) == DEFAULT_MAX_TURNS


async def test_refusal_stops_with_error(tmp_path):
    refusal = response(text(""))
    refusal.stop_reason = "refusal"
    investigator, _, _ = make([refusal], tmp_path=tmp_path)
    result = await investigator.investigate("job failed")
    assert result.stop_reason == "error"
    assert "refusal" in result.error_message


async def test_max_tokens_truncation_stops_without_running_tools(tmp_path):
    # A truncated turn may hold a half-written tool_use; it must never be executed.
    truncated = response(text("Looking..."), tool_use("get_job_status", JOB))
    truncated.stop_reason = "max_tokens"
    investigator, messages, session = make([truncated], tmp_path=tmp_path, max_tokens=512)
    result = await investigator.investigate("job failed")

    assert result.stop_reason == "error"
    assert result.error_message == "model output hit max_tokens (512); raise --max-tokens"
    assert result.report is None
    assert session.calls == []
    assert len(messages.calls) == 1
    events = trace_events(result)
    assert [e["event"] for e in events if e["event"] == "truncated_response"] == [
        "truncated_response"
    ]
    assert events[-1]["event"] == "final"


def test_max_tokens_default(tmp_path):
    assert Investigator(client=FakeAnthropic([]), trace_dir=tmp_path).max_tokens == 8192


# ---- ordering, thinking, redaction, trace ----------------------------------------------


async def test_parallel_tool_uses_run_in_order_with_one_result_message(tmp_path):
    calls = [
        tool_use("get_job_status", JOB),
        tool_use("search_logs", JOB),
        tool_use("query_metric", {**JOB, "metric": "cpu"}),
    ]
    session = FakeSession(
        results={
            "get_job_status": ("status", False),
            "search_logs": ("logs", False),
            "query_metric": ("metric", False),
        }
    )
    investigator, messages, _ = make(
        [response(*calls), response(submit())], session=session, tmp_path=tmp_path
    )
    await investigator.investigate("job failed")

    assert [name for name, _ in session.calls] == ["get_job_status", "search_logs", "query_metric"]
    second = messages.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    results = second[-1]["content"]
    assert [r["tool_use_id"] for r in results] == [c.id for c in calls]
    assert [r["content"] for r in results] == ["status", "logs", "metric"]


async def test_thinking_blocks_are_passed_back_unchanged(tmp_path):
    thinking = SimpleNamespace(type="thinking", thinking="", signature="sig-abc")
    call = tool_use("get_job_status", JOB)
    investigator, messages, _ = make(
        [response(thinking, call), response(submit())], tmp_path=tmp_path
    )
    await investigator.investigate("job failed")

    assistant = messages.calls[1]["messages"][1]["content"]
    assert assistant[0] == {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    assert assistant[1]["type"] == "tool_use"


SECRET_RESULT = "Request: password=FAKE-SECRET-123 Authorization: Bearer FAKE-TOKEN-abcdef12"


async def test_secrets_redacted_for_model_and_trace(tmp_path):
    session = FakeSession(results={"search_logs": (SECRET_RESULT, False)})
    investigator, messages, _ = make(
        [
            # The model's own tool arguments carry a secret too: the trace must hide it.
            response(tool_use("search_logs", {**JOB, "query": "token=FAKE-ARG-9999"})),
            response(submit()),
        ],
        session=session,
        tmp_path=tmp_path,
    )
    result = await investigator.investigate("job failed, api_key=FAKE-REPORT-KEY")

    sent_back = last_user_content(messages.calls[1])[0]["content"]
    assert "FAKE-" not in sent_back
    assert "password=[REDACTED]" in sent_back
    assert "Bearer [REDACTED]" in sent_back
    trace_text = open(result.trace_path).read()
    assert "FAKE-" not in trace_text
    assert "[REDACTED]" in trace_text


async def test_every_trace_line_is_json_with_event_and_tokens(tmp_path):
    session = FakeSession(results={"search_logs": (SECRET_RESULT, False)})
    investigator, _, _ = make(
        [response(tool_use("search_logs", JOB)), response(submit())],
        session=session,
        tmp_path=tmp_path,
    )
    result = await investigator.investigate("job failed")

    events = trace_events(result)  # json.loads on every line
    assert all("event" in e for e in events)
    model_events = [e for e in events if e["event"] == "model_response"]
    assert model_events and all(e["input_tokens"] == 100 for e in model_events)
    assert all(e["output_tokens"] == 20 for e in model_events)
    assert events[-1]["totals"]["input_tokens"] == 200
    assert "FAKE-" not in open(result.trace_path).read()


# ---- failures ---------------------------------------------------------------------------


async def test_investigation_timeout(tmp_path):
    async def slow(_kwargs):
        await asyncio.sleep(5)

    investigator, _, _ = make([slow], tmp_path=tmp_path, investigation_timeout_s=0.2)
    result = await investigator.investigate("job failed")

    assert result.stop_reason == "timeout"
    assert result.report is None
    assert result.elapsed_s < 2
    assert trace_events(result)[-1]["event"] == "final"


async def test_api_error_does_not_leak_key(tmp_path, monkeypatch):
    fake_key = "sk-ant-api03-FAKE-TEST-KEY-0123456789"
    monkeypatch.setenv("ANTHROPIC_API_KEY", fake_key)
    error = anthropic.InternalServerError(
        f"upstream failure while using key {fake_key}",
        response=httpx2.Response(500, request=_api_request()),
        body=None,
    )
    investigator, _, _ = make([error], tmp_path=tmp_path)
    result = await investigator.investigate("job failed")

    assert result.stop_reason == "error"
    assert "500" in result.error_message
    assert fake_key not in result.error_message
    assert fake_key not in open(result.trace_path).read()


async def test_missing_key_raises_before_any_session(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    factory = session_factory(FakeSession())
    with pytest.raises(MissingApiKeyError):
        Investigator(session_factory=factory, trace_dir=tmp_path)
    assert factory.opened == 0


def test_model_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("ROOTSIGNAL_AGENT_MODEL", raising=False)
    assert Investigator(client=FakeAnthropic([]), trace_dir=tmp_path).model == "claude-sonnet-5-5"
    monkeypatch.setenv("ROOTSIGNAL_AGENT_MODEL", "claude-test-model")
    assert Investigator(client=FakeAnthropic([]), trace_dir=tmp_path).model == "claude-test-model"


# ---- integration: real stdio server, fake model ----------------------------------------


async def test_real_server_with_fake_model(tmp_path):
    job = load_scenarios()["auth_expired_01"].job_name
    report = {
        **VALID_REPORT,
        "root_cause_category": "auth_expired",
        "evidence": [
            {
                "tool": "search_logs",
                "quote": "client secret for svc-cms-sync expired on 2026-10-12",
                "why_it_matters": "The credential expired.",
            }
        ],
    }
    client = FakeAnthropic(
        [
            response(tool_use("get_job_status", {"job_name": job})),
            response(tool_use("search_logs", {"job_name": job, "limit": 100})),
            response(submit(report)),
        ]
    )
    investigator = Investigator(client=client, session_factory=platform_session, trace_dir=tmp_path)
    result = await investigator.investigate("cms sync is failing", scenario_id="auth_expired_01")

    assert result.stop_reason == "submitted", result.error_message
    assert result.tool_calls_used == 2
    logs_result = last_user_content(client.messages.calls[2])[0]
    assert logs_result["is_error"] is False
    assert "Bearer [REDACTED]" in logs_result["content"]
    assert "FAKE-" not in open(result.trace_path).read()
    assert list(tmp_path.glob("*.server.log"))  # child stderr went to a file
