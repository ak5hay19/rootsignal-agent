"""Client helper: spawn the stdio server for one scenario and yield an initialized session."""

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from rootsignal_agent.sim.engine import SCENARIO_ENV_VAR

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def platform_session(scenario_id: str | None = None) -> AsyncIterator[ClientSession]:
    # stdio_client only passes a small safe subset of the parent env by default, so we
    # hand it the full environment explicitly (the child needs e.g. the venv and HF cache).
    env = dict(os.environ)
    if scenario_id:
        env[SCENARIO_ENV_VAR] = scenario_id
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "rootsignal_agent.mcp_server"],
        env=env,
        cwd=PROJECT_ROOT,  # so `-m rootsignal_agent...` resolves without installing the package
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session
