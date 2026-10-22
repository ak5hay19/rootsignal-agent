"""MCP server exposing six read-only tools over the simulated platform (stdio).

stdout carries the protocol, so this module only logs (to stderr) and never prints.
The server is the authoritative redaction point: every result goes through
redact() -> json.dumps -> truncate_result before the model sees it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from rootsignal_agent.agent.guardrails import ALLOWED_REMEDIATIONS, redact, truncate_result
from rootsignal_agent.mcp_server.tools.get_job_status import get_job_status
from rootsignal_agent.mcp_server.tools.list_recent_incidents import list_recent_incidents
from rootsignal_agent.mcp_server.tools.propose_remediation import (
    ACTION_EFFECTS,
    propose_remediation,
)
from rootsignal_agent.mcp_server.tools.query_metric import query_metric
from rootsignal_agent.mcp_server.tools.search_logs import search_logs
from rootsignal_agent.mcp_server.tools.search_runbooks import search_runbooks
from rootsignal_agent.rag.index import RunbookIndex
from rootsignal_agent.sim.engine import PlatformEngine, SimError
from rootsignal_agent.sim.metrics import METRIC_CATALOG

logger = logging.getLogger(__name__)

SERVER_NAME = "rootsignal-platform"


def _metric_lines() -> str:
    return "\n".join(
        f"- {name} ({info['unit']}): {info['description']}" for name, info in METRIC_CATALOG.items()
    )


def _action_lines() -> str:
    return "\n".join(f"- {a}: {ACTION_EFFECTS[a]}" for a in sorted(ALLOWED_REMEDIATIONS))


QUERY_METRIC_DESCRIPTION = (
    "Get a metric time series for a job over the last window_minutes (1-360, default 60), "
    "with min/max/avg/last. Valid metrics:\n" + _metric_lines()
)

PROPOSE_REMEDIATION_DESCRIPTION = (
    "Propose a remediation for a job. This is a DRY RUN: it NEVER executes anything. It "
    "validates the request and returns what would happen, and a human must approve and run "
    "it. Provide a reason citing your evidence. Allowed actions:\n" + _action_lines()
)


def _respond(payload: Any) -> str:
    """The one place a tool result is prepared for the model."""
    return truncate_result(json.dumps(redact(payload), default=str))


def _guard(fn: Callable[[], Any]) -> str:
    """Run a tool body. Expected failures (bad arguments, unknown job/metric) become
    ToolError, which the SDK returns as an isError result carrying our message. Anything
    else is a bug: the SDK logs it and sends only a generic error, so no internals leak."""
    try:
        return _respond(fn())
    except (SimError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


def create_server(
    engine: PlatformEngine | None = None,
    index_factory: Callable[[], RunbookIndex] | None = None,
) -> MCPServer:
    engine = engine or PlatformEngine.from_dir()  # active scenario from the env var
    make_index = index_factory or RunbookIndex.from_dir
    cache: dict[str, RunbookIndex] = {}

    def get_index() -> RunbookIndex:
        # Built on first use (loads the embedding model, a few seconds) and then reused,
        # so the other tools stay fast.
        if "index" not in cache:
            logger.info("building runbook index")
            cache["index"] = make_index()
        return cache["index"]

    server = MCPServer(SERVER_NAME)

    @server.tool(
        name="get_job_status",
        description=(
            "Get a job's current state: status, start/end times, attempt number, last "
            "successful run and exit reason. Start here once you know the job name."
        ),
    )
    def _get_job_status(job_name: str) -> str:
        return _guard(lambda: get_job_status(engine, job_name))

    @server.tool(
        name="search_logs",
        description=(
            "Search a job's logs. Returns the most recent matching lines in chronological "
            'order (oldest first). Try level="ERROR" first, then widen. query is a '
            "case-insensitive substring match; level is INFO, WARN or ERROR; limit is "
            "1-100 (default 20)."
        ),
    )
    def _search_logs(
        job_name: str, query: str | None = None, limit: int = 20, level: str | None = None
    ) -> str:
        return _guard(lambda: search_logs(engine, job_name, query, limit, level))

    @server.tool(name="query_metric", description=QUERY_METRIC_DESCRIPTION)
    def _query_metric(metric: str, job_name: str, window_minutes: int = 60) -> str:
        return _guard(lambda: query_metric(engine, metric, job_name, window_minutes))

    @server.tool(
        name="search_runbooks",
        description=(
            "Search operational runbooks. Pass the specific symptoms and error messages you "
            "observed in logs and metrics, not just the user's description. Returns up to 3 "
            "candidate runbooks. Check each candidate's 'Commonly confused with' section "
            "against your evidence before choosing one."
        ),
    )
    def _search_runbooks(query: str) -> str:
        return _guard(lambda: search_runbooks(get_index(), query))

    @server.tool(
        name="list_recent_incidents",
        description=(
            "List a team's recent incidents. Use this when the user does not name a job, "
            "to find which job they mean."
        ),
    )
    def _list_recent_incidents(team: str) -> str:
        return _guard(lambda: list_recent_incidents(engine, team))

    @server.tool(name="propose_remediation", description=PROPOSE_REMEDIATION_DESCRIPTION)
    def _propose_remediation(action: str, job_name: str, reason: str) -> str:
        return _guard(lambda: propose_remediation(engine, action, job_name, reason))

    return server
