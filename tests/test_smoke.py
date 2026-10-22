import importlib

import pytest

PACKAGES = [
    "rootsignal_agent",
    "rootsignal_agent.sim",
    "rootsignal_agent.mcp_server",
    "rootsignal_agent.rag",
    "rootsignal_agent.agent",
    "rootsignal_agent.slack_bot",
    "rootsignal_agent.evals",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name):
    assert importlib.import_module(name) is not None
