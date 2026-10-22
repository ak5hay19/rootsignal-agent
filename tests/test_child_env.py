"""build_child_env: the MCP server child must not inherit the parent's secrets."""

from rootsignal_agent.mcp_server.client import build_child_env
from rootsignal_agent.sim.engine import SCENARIO_ENV_VAR

BASE = {
    "ANTHROPIC_API_KEY": "sk-ant-FAKE",
    "SLACK_BOT_TOKEN": "xoxb-FAKE",
    "DB_PASSWORD": "hunter2-FAKE",
    "AWS_SECRET_ACCESS_KEY": "aws-FAKE",
    "GOOGLE_CREDENTIALS": "cred-FAKE",
    "github_token": "ghp-FAKE",  # lower case: the match ignores case
    "PATH": "/usr/bin:/bin",
    "HOME": "/home/test",
    "VIRTUAL_ENV": "/venv",
}
SECRET_NAMES = {
    "ANTHROPIC_API_KEY",
    "SLACK_BOT_TOKEN",
    "DB_PASSWORD",
    "AWS_SECRET_ACCESS_KEY",
    "GOOGLE_CREDENTIALS",
    "github_token",
}


def test_secrets_removed_and_path_kept():
    env = build_child_env(BASE, "oom_01")
    assert not SECRET_NAMES & env.keys()
    assert "FAKE" not in " ".join(env.values())
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/home/test"
    assert env["VIRTUAL_ENV"] == "/venv"


def test_scenario_is_set_and_base_is_not_modified():
    base = dict(BASE)
    assert build_child_env(base, "oom_01")[SCENARIO_ENV_VAR] == "oom_01"
    assert base == BASE


def test_no_scenario_leaves_the_variable_alone():
    assert SCENARIO_ENV_VAR not in build_child_env(BASE, None)
    assert build_child_env({SCENARIO_ENV_VAR: "x"}, None)[SCENARIO_ENV_VAR] == "x"
