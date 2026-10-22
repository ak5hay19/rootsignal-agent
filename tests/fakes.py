"""Scripted fakes for the agent loop tests: no network, no API key, no MCP server."""

from __future__ import annotations

import asyncio
import copy
import itertools
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from rootsignal_agent.agent.guardrails import ALLOWED_TOOLS

_ids = itertools.count(1)

VALID_REPORT: dict[str, Any] = {
    "root_cause_category": "oom",
    "summary": "The job ran out of executor memory.",
    "evidence": [
        {
            "tool": "search_logs",
            "quote": "java.lang.OutOfMemoryError: Java heap space",
            "why_it_matters": "Explicit out-of-memory error at the failure time.",
        }
    ],
    "alternatives_considered": [
        {"category": "data_skew", "why_rejected": "All tasks used similar memory."}
    ],
    "runbook": "oom.md",
    "proposed_remediation": {"action": "increase_memory", "rationale": "Heap exhausted."},
    "confidence": "high",
}


# ---- fake Anthropic client --------------------------------------------------------------


def text(value: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=value)


def tool_use(name: str, tool_input: dict[str, Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_use", id=f"toolu_{next(_ids)}", name=name, input=tool_input or {}
    )


def submit(report: dict[str, Any] | None = None) -> SimpleNamespace:
    return tool_use("submit_report", report if report is not None else VALID_REPORT)


def response(*blocks: SimpleNamespace, input_tokens: int = 100, output_tokens: int = 20):
    has_tool = any(b.type == "tool_use" for b in blocks)
    return SimpleNamespace(
        content=list(blocks),
        stop_reason="tool_use" if has_tool else "end_turn",
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


ScriptItem = SimpleNamespace | Exception | Callable[[dict[str, Any]], Awaitable[Any]]


class FakeMessages:
    """messages.create pops the next scripted item: a response, an exception to raise,
    or an async callable (e.g. one that sleeps). Every call's kwargs are recorded."""

    def __init__(self, script: list[ScriptItem]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        # Deep copy: the loop keeps appending to the same messages list.
        self.calls.append(copy.deepcopy(kwargs))
        if not self.script:
            raise AssertionError("FakeAnthropic script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return await item(kwargs)
        return item


class FakeAnthropic:
    def __init__(self, script: list[ScriptItem]) -> None:
        self.messages = FakeMessages(script)


# ---- fake MCP session -------------------------------------------------------------------


class FakeSession:
    """results maps a tool name to (text, is_error). Unlisted tools return '{"ok": true}'."""

    def __init__(
        self,
        results: dict[str, tuple[str, bool]] | None = None,
        delay_s: float = 0.0,
        tool_names: frozenset[str] = ALLOWED_TOOLS,
    ) -> None:
        self.results = results or {}
        self.delay_s = delay_s
        self.tool_names = tool_names
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> SimpleNamespace:
        tools = [
            SimpleNamespace(
                name=name,
                description=f"{name} (fake)",
                input_schema={"type": "object", "properties": {}},
            )
            for name in sorted(self.tool_names)
        ]
        return SimpleNamespace(tools=tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> SimpleNamespace:
        self.calls.append((name, arguments))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        result_text, is_error = self.results.get(name, ('{"ok": true}', False))
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=result_text)], is_error=is_error
        )


def session_factory(session: Any) -> Callable[..., Any]:
    """A platform_session stand-in that yields `session` and counts how often it opened."""

    @asynccontextmanager
    async def factory(scenario_id: str | None = None, errlog: Any = None):
        factory.opened += 1  # type: ignore[attr-defined]
        yield session

    factory.opened = 0  # type: ignore[attr-defined]
    return factory
