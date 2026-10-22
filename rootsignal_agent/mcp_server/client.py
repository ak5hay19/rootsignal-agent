"""Client helper: spawn the stdio server for one scenario and yield an initialized session."""

import os
import re
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TextIO

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from rootsignal_agent.sim.engine import SCENARIO_ENV_VAR

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Least privilege: the MCP server only reads local scenario files, so it never needs the
# parent's credentials. Any variable whose name contains one of these words is dropped.
SECRET_NAME = re.compile(r"API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)


def build_child_env(base: Mapping[str, str], scenario_id: str | None) -> dict[str, str]:
    """The environment for the MCP server child: a copy of base with secrets removed."""
    env = {name: value for name, value in base.items() if not SECRET_NAME.search(name)}
    if scenario_id:
        env[SCENARIO_ENV_VAR] = scenario_id
    return env


@asynccontextmanager
async def platform_session(
    scenario_id: str | None = None, errlog: TextIO | None = None
) -> AsyncIterator[ClientSession]:
    """errlog receives the child process's stderr (model loading, warnings). It must be a
    real file with a file descriptor. None keeps the default: the parent's stderr."""
    # stdio_client only passes a small safe subset of the parent env by default, so we
    # hand it the environment explicitly (the child needs e.g. the venv and HF cache),
    # minus anything that looks like a secret.
    env = build_child_env(os.environ, scenario_id)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "rootsignal_agent.mcp_server"],
        env=env,
        cwd=PROJECT_ROOT,  # so `-m rootsignal_agent...` resolves without installing the package
    )
    stderr = errlog if errlog is not None else sys.stderr
    async with (
        stdio_client(params, errlog=stderr) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session
