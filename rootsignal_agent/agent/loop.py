"""The investigation loop: Claude calls MCP tools until it submits a structured report.

The model never touches the platform directly. It asks for tools; this loop checks each
request against the guardrails, forwards allowed ones to the MCP server, and sends the
(redacted, truncated) results back. The run ends when the model calls the local
submit_report tool with a valid report, or when a limit is hit.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
from pydantic import ValidationError

from rootsignal_agent.agent.guardrails import (
    ALLOWED_TOOLS,
    DEFAULT_INVESTIGATION_TIMEOUT_S,
    DEFAULT_MAX_TOOL_CALLS,
    DEFAULT_MAX_TURNS,
    DEFAULT_TOOL_TIMEOUT_S,
    REDACTED,
    redact,
    redact_text,
    truncate_result,
)
from rootsignal_agent.agent.models import (
    SUBMIT_TOOL,
    InvestigationReport,
    InvestigationResult,
    StopReason,
)
from rootsignal_agent.agent.prompts import get_system_prompt
from rootsignal_agent.mcp_server.client import platform_session

DEFAULT_MODEL = "claude-sonnet-5-5"
MODEL_ENV_VAR = "ROOTSIGNAL_AGENT_MODEL"
API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"

SUBMIT_TOOL_NAME: str = SUBMIT_TOOL["name"]
FORCE_AT_TIMEOUT_FRACTION = 0.75
MAX_NUDGES = 2
MAX_INVALID_SUBMISSIONS = 2
MAX_ERROR_MESSAGE_CHARS = 300
DEFAULT_MAX_TOKENS = 8192

TOOL_CHOICE_AUTO: dict[str, Any] = {"type": "auto"}
TOOL_CHOICE_SUBMIT: dict[str, Any] = {"type": "tool", "name": SUBMIT_TOOL_NAME}

NUDGE_TEXT = "Call submit_report now with your findings."
FORCE_TEXT = {
    "tool_budget_spent": "You have used all of your tool calls.",
    "time_almost_up": "The investigation is almost out of time.",
    "nudges_used": "You have not called submit_report yet.",
}
FORCE_SUFFIX = (
    " Call submit_report now with your findings so far. If the evidence is not conclusive, "
    'report "unknown" with low confidence.'
)

# A session factory takes a scenario id and an errlog file and yields an MCP ClientSession
# (or a test fake with list_tools() and call_tool()).
SessionFactory = Callable[..., AbstractAsyncContextManager[Any]]
EventCallback = Callable[[dict[str, Any]], None]


class MissingApiKeyError(RuntimeError):
    """No client was injected and ANTHROPIC_API_KEY is not set."""


@dataclass
class _RunState:
    """Counters for one investigation, kept so a partial result can be reported."""

    started: float
    tool_calls_used: int = 0
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    report: InvestigationReport | None = None
    error_message: str | None = None


class TraceWriter:
    """One JSONL file per run. Each event is redacted, written and flushed immediately,
    so a partial trace survives a crash."""

    def __init__(self, path: Path, on_event: EventCallback | None = None) -> None:
        self.path = path
        self._file = path.open("w", encoding="utf-8")
        self._on_event = on_event

    def write(self, event: str, **fields: Any) -> None:
        record = redact({"event": event, "ts": datetime.now(UTC).isoformat(), **fields})
        self._file.write(json.dumps(record, default=str) + "\n")
        self._file.flush()
        if self._on_event:
            self._on_event(record)

    def close(self) -> None:
        self._file.close()


class Investigator:
    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        prompt_variant: str = "default",
        max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
        investigation_timeout_s: float = DEFAULT_INVESTIGATION_TIMEOUT_S,
        tool_timeout_s: float = DEFAULT_TOOL_TIMEOUT_S,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        trace_dir: str | Path = "traces",
        session_factory: SessionFactory = platform_session,
        on_event: EventCallback | None = None,
    ) -> None:
        if client is None:
            # Checked here, before any MCP server is spawned. Only presence is checked;
            # the value is never read into our own code or printed.
            if not os.environ.get(API_KEY_ENV_VAR, "").strip():
                raise MissingApiKeyError(
                    f"{API_KEY_ENV_VAR} is not set. Add it to .env (see .env.example) "
                    "or export it in your shell."
                )
            client = anthropic.AsyncAnthropic(max_retries=2)
        self.client = client
        self.model = model or os.environ.get(MODEL_ENV_VAR) or DEFAULT_MODEL
        self.prompt_variant = prompt_variant
        self.system_prompt = get_system_prompt(prompt_variant, max_tool_calls)  # fails fast
        self.max_tool_calls = max_tool_calls
        self.investigation_timeout_s = investigation_timeout_s
        self.tool_timeout_s = tool_timeout_s
        self.max_tokens = max_tokens
        self.trace_dir = Path(trace_dir)
        self.session_factory = session_factory
        self.on_event = on_event
        # Some models reject a forced tool_choice with a 400. Once seen, stop sending it.
        self._forced_tool_choice_supported = True

    # ---- public entry point ---------------------------------------------------------

    async def investigate(
        self, user_report: str, scenario_id: str | None = None
    ) -> InvestigationResult:
        run_id = uuid.uuid4().hex[:8]
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        trace_path = self.trace_dir / f"{stamp}_{scenario_id or 'adhoc'}_{run_id}.jsonl"
        trace = TraceWriter(trace_path, self.on_event)
        state = _RunState(started=time.monotonic())
        stop_reason: StopReason = "error"
        trace.write(
            "run_start",
            run_id=run_id,
            scenario=scenario_id,
            model=self.model,
            prompt_variant=self.prompt_variant,
            limits={
                "max_tool_calls": self.max_tool_calls,
                "max_turns": DEFAULT_MAX_TURNS,
                "investigation_timeout_s": self.investigation_timeout_s,
                "tool_timeout_s": self.tool_timeout_s,
                "max_tokens": self.max_tokens,
            },
            user_report=user_report,
        )
        # Error handling: nothing escapes. Every failure becomes a stop_reason plus a short,
        # scrubbed error_message, and the trace always gets a "final" line.
        try:
            async with asyncio.timeout(self.investigation_timeout_s):
                stop_reason = await self._run(user_report, scenario_id, run_id, state, trace)
        except TimeoutError:
            stop_reason, state.report = "timeout", None
            state.error_message = f"investigation exceeded {self.investigation_timeout_s}s"
        except anthropic.APIError as exc:
            stop_reason, state.report = "error", None
            state.error_message = _describe_api_error(exc)
        except Exception as exc:  # a bug or a dead MCP server; report it, don't crash
            stop_reason, state.report = "error", None
            state.error_message = _scrub(f"{type(exc).__name__}: {exc}")

        result = InvestigationResult(
            stop_reason=stop_reason,
            report=state.report,
            tool_calls_used=state.tool_calls_used,
            turns=state.turns,
            input_tokens=state.input_tokens,
            output_tokens=state.output_tokens,
            elapsed_s=round(time.monotonic() - state.started, 2),
            trace_path=str(trace_path),
            error_message=state.error_message,
        )
        trace.write(
            "final",
            stop_reason=stop_reason,
            report=result.report.model_dump(mode="json") if result.report else None,
            totals={
                "tool_calls_used": result.tool_calls_used,
                "turns": result.turns,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "elapsed_s": result.elapsed_s,
            },
            error_message=result.error_message,
        )
        trace.close()
        return result

    # ---- the loop -------------------------------------------------------------------

    async def _run(
        self,
        user_report: str,
        scenario_id: str | None,
        run_id: str,
        state: _RunState,
        trace: TraceWriter,
    ) -> StopReason:
        # The child server's stderr (model loading, HuggingFace warnings) goes to a file
        # next to the trace instead of the terminal.
        with (self.trace_dir / f"{run_id}.server.log").open("w") as errlog:
            async with self.session_factory(scenario_id, errlog=errlog) as session:
                tools = await self._tool_definitions(session)
                return await self._loop(session, tools, user_report, state, trace)

    async def _loop(
        self,
        session: Any,
        tools: list[dict[str, Any]],
        user_report: str,
        state: _RunState,
        trace: TraceWriter,
    ) -> StopReason:
        # Loop algorithm (one iteration = one model call):
        #   1. Stop with "max_turns" once DEFAULT_MAX_TURNS model calls have been made.
        #   2. Decide whether to FORCE submission: the tool budget is spent, or 75% of the
        #      investigation timeout has passed, or both nudges were used. Forcing is
        #      sticky. When forced we send tool_choice=submit_report and also say so in
        #      text, because some models reject a forced tool_choice (see _call_model).
        #   3. Call the model, add its token usage, append its turn to the history.
        #   4. No tool call -> append a nudge and loop (after two nudges, step 2 forces).
        #   5. Otherwise handle each tool_use block in order and send every result back in
        #      ONE user message. A valid submit_report ends the run; a second invalid one
        #      ends it with "error". Platform tools pass the allowlist and budget checks.
        # The loop always terminates: every iteration makes one model call, and step 1
        # caps those. The asyncio.timeout in investigate() bounds the wall clock.
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"type": "text", "text": _first_message(user_report)}]}
        ]
        nudges = 0
        invalid_submissions = 0
        force_reason: str | None = None

        while True:
            if state.turns >= DEFAULT_MAX_TURNS:
                state.error_message = f"no report after {DEFAULT_MAX_TURNS} model calls"
                return "max_turns"

            if force_reason is None:
                force_reason = self._force_reason(state, nudges)
                if force_reason:
                    trace.write("forced_submit", reason=force_reason)
                    # The last message has not been sent yet, so adding to it keeps the
                    # history append-only from the API's point of view.
                    messages[-1]["content"].append(
                        {"type": "text", "text": FORCE_TEXT[force_reason] + FORCE_SUFFIX}
                    )

            response = await self._call_model(tools, messages, force_reason is not None, trace)
            state.turns += 1
            state.input_tokens += response.usage.input_tokens
            state.output_tokens += response.usage.output_tokens
            trace.write("model_response", **_response_summary(state.turns, response))

            # A turn cut off by max_tokens can end in a half-written tool_use whose input is
            # incomplete. Never act on it: stop here, before any block is handled.
            if response.stop_reason == "max_tokens":
                trace.write("truncated_response", turn=state.turns, max_tokens=self.max_tokens)
                state.error_message = (
                    f"model output hit max_tokens ({self.max_tokens}); raise --max-tokens"
                )
                return "error"

            assistant_content = _assistant_content(response.content)
            if assistant_content:
                messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "refusal":
                state.error_message = "the model declined to continue (stop_reason=refusal)"
                return "error"

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                nudges += 1
                messages.append({"role": "user", "content": [{"type": "text", "text": NUDGE_TEXT}]})
                continue

            results: list[dict[str, Any]] = []
            for block in tool_uses:
                if block.name != SUBMIT_TOOL_NAME:
                    results.append(await self._call_platform_tool(session, block, state, trace))
                    continue
                try:
                    state.report = InvestigationReport.model_validate(block.input)
                except ValidationError as exc:
                    invalid_submissions += 1
                    trace.write(
                        "report_validation_error", attempt=invalid_submissions, errors=str(exc)
                    )
                    if invalid_submissions >= MAX_INVALID_SUBMISSIONS:
                        state.error_message = "submit_report input was invalid twice"
                        return "error"
                    results.append(
                        _tool_result(block.id, f"Invalid report, fix it and resubmit:\n{exc}", True)
                    )
                    continue
                # A valid report ends the run. Any tool_use blocks after it are dropped,
                # which is fine because no further model call is made.
                return "budget_exhausted" if force_reason == "tool_budget_spent" else "submitted"

            messages.append({"role": "user", "content": results})

    def _force_reason(self, state: _RunState, nudges: int) -> str | None:
        if state.tool_calls_used >= self.max_tool_calls:
            return "tool_budget_spent"
        elapsed = time.monotonic() - state.started
        if elapsed >= FORCE_AT_TIMEOUT_FRACTION * self.investigation_timeout_s:
            return "time_almost_up"
        if nudges >= MAX_NUDGES:
            return "nudges_used"
        return None

    async def _call_model(
        self,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        forced: bool,
        trace: TraceWriter,
    ) -> Any:
        tool_choice = (
            TOOL_CHOICE_SUBMIT
            if forced and self._forced_tool_choice_supported
            else TOOL_CHOICE_AUTO
        )
        # No temperature: the installed SDK (anthropic 2.x, API version 2026-10-21) has no
        # sampling parameters, and the API rejects them on every model at that version.
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system_prompt,
            "tools": tools,
            "messages": messages,
        }
        try:
            return await self.client.messages.create(**kwargs, tool_choice=tool_choice)
        except anthropic.BadRequestError as exc:
            # Newer models (e.g. claude-sonnet-5-5) reject tool_choice "tool" with a 400.
            # Retry once with "auto"; the forcing text already in the messages still asks
            # for submit_report, and the max_turns cap still bounds the run.
            if tool_choice is TOOL_CHOICE_AUTO or "tool_choice" not in str(exc):
                raise
            self._forced_tool_choice_supported = False
            trace.write("forced_tool_choice_rejected", error=_describe_api_error(exc))
            return await self.client.messages.create(**kwargs, tool_choice=TOOL_CHOICE_AUTO)

    async def _call_platform_tool(
        self, session: Any, block: Any, state: _RunState, trace: TraceWriter
    ) -> dict[str, Any]:
        trace.write("tool_call", turn=state.turns, name=block.name, arguments=block.input)
        started = time.monotonic()

        if block.name not in ALLOWED_TOOLS:
            text, is_error = f"tool not allowed: {block.name}", True
        elif state.tool_calls_used >= self.max_tool_calls:
            text, is_error = "tool budget exhausted, call submit_report now", True
        else:
            # Counted before the call, so failed and timed-out calls use budget too.
            state.tool_calls_used += 1
            try:
                result = await asyncio.wait_for(
                    session.call_tool(block.name, block.input), self.tool_timeout_s
                )
                text = _result_text(result)
                is_error = bool(getattr(result, "is_error", False))
            except TimeoutError:
                text, is_error = f"tool {block.name} timed out after {self.tool_timeout_s}s", True
            except Exception as exc:  # a broken session; tell the model, keep going
                text, is_error = (
                    _scrub(f"tool {block.name} failed: {type(exc).__name__}: {exc}"),
                    True,
                )

        # Defense in depth: the server already redacts and truncates; do it again here so
        # a misbehaving server cannot leak a secret into the model's context.
        text = truncate_result(redact_text(text))
        trace.write(
            "tool_result",
            turn=state.turns,
            name=block.name,
            is_error=is_error,
            duration_ms=round((time.monotonic() - started) * 1000),
            content=text,
        )
        return _tool_result(block.id, text, is_error)

    async def _tool_definitions(self, session: Any) -> list[dict[str, Any]]:
        listed = (await session.list_tools()).tools
        # Only allowlisted tools are offered to the model; the call path checks again.
        tools = [
            {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in listed
            if t.name in ALLOWED_TOOLS
        ]
        return [*tools, SUBMIT_TOOL]


# ---- helpers -------------------------------------------------------------------------


def _first_message(user_report: str) -> str:
    return (
        "A user reported the following issue:\n"
        f"<user_report>\n{user_report}\n</user_report>\n"
        "Investigate with the tools, then call submit_report."
    )


def _assistant_content(blocks: list[Any]) -> list[dict[str, Any]]:
    """Rebuild the assistant turn as plain request params, field by field.

    Thinking blocks are passed back unchanged (with their signature), as the API requires
    when a model thinks between tool calls. Empty text blocks are dropped (the API rejects
    them), and any other block type is ignored since we enable no server tools."""
    content: list[dict[str, Any]] = []
    for b in blocks:
        if b.type == "text" and b.text:
            content.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        elif b.type == "thinking":
            content.append({"type": "thinking", "thinking": b.thinking, "signature": b.signature})
        elif b.type == "redacted_thinking":
            content.append({"type": "redacted_thinking", "data": b.data})
    return content


def _tool_result(tool_use_id: str, text: str, is_error: bool) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": text,
        "is_error": is_error,
    }


def _result_text(result: Any) -> str:
    # An MCP CallToolResult holds a list of content parts; our server returns one text part.
    parts = [p.text for p in getattr(result, "content", None) or [] if getattr(p, "text", None)]
    return "\n".join(parts) or "(empty result)"


def _response_summary(turn: int, response: Any) -> dict[str, Any]:
    return {
        "turn": turn,
        "stop_reason": response.stop_reason,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "text": [b.text[:500] for b in response.content if b.type == "text" and b.text],
        "thinking_blocks": sum(1 for b in response.content if b.type == "thinking"),
        "tool_uses": [
            {"name": b.name, "input": b.input} for b in response.content if b.type == "tool_use"
        ],
    }


def _scrub(text: str) -> str:
    """Make an error message safe to show and store: no API key, no secrets, short."""
    key = os.environ.get(API_KEY_ENV_VAR, "").strip()
    if key:
        text = text.replace(key, REDACTED)
    return truncate_result(redact_text(text), MAX_ERROR_MESSAGE_CHARS)


def _describe_api_error(exc: anthropic.APIError) -> str:
    # Only the class, status and the API's own message: never the request or its headers.
    if isinstance(exc, anthropic.APIStatusError):
        return _scrub(
            f"Anthropic API error {exc.status_code} ({type(exc).__name__}): {exc.message}"
        )
    return _scrub(f"Anthropic API error ({type(exc).__name__}): {exc.message}")
