import pytest

from rootsignal_agent.agent.guardrails import (
    ALLOWED_REMEDIATIONS,
    ALLOWED_TOOLS,
    DEFAULT_MAX_TURNS,
    MAX_TOOL_RESULT_CHARS,
    redact,
    redact_text,
    truncate_result,
)
from rootsignal_agent.sim.engine import load_scenarios

SECRET_CASES = [
    ("api_key=abc123secret", "api_key=[REDACTED]"),
    ("apikey: abc123secret", "apikey: [REDACTED]"),
    ("api-key=abc123secret", "api-key=[REDACTED]"),
    ('{"secret": "s3cr3t-value"}', '{"secret": "[REDACTED]"}'),
    ("client_secret=s3cr3t", "client_secret=[REDACTED]"),
    ("password=hunter2", "password=[REDACTED]"),
    ("passwd: hunter2", "passwd: [REDACTED]"),
    ("pwd=hunter2", "pwd=[REDACTED]"),
    ("token=abcd1234", "token=[REDACTED]"),
    ("access_key=abcd1234", "access_key=[REDACTED]"),
    ('"token": "abcd1234"', '"token": "[REDACTED]"'),
    ("Authorization: Bearer abcdefgh12345", "Authorization: Bearer [REDACTED]"),
    ("Bearer abcdefgh12345", "Bearer [REDACTED]"),
    ("key AKIAABCDEFGHIJKLMNOP end", "key [REDACTED] end"),
    ("t=ghp_" + "a" * 36, "t=[REDACTED]"),
    ("jwt eyJhbGciOiJI.eyJzdWIiOiIx.sig_n-1 x", "jwt [REDACTED] x"),
    (
        "k:\n-----BEGIN RSA PRIVATE KEY-----\nMIIE\nabc\n-----END RSA PRIVATE KEY-----\nafter",
        "k:\n[REDACTED]\nafter",
    ),
]

INNOCENT = [
    "token expired at 02:11",
    "password rotation failed",
    "Authorization failed: 401",
    "the bearer of bad news",
]


@pytest.mark.parametrize(("raw", "expected"), SECRET_CASES)
def test_redacts_secrets(raw, expected):
    assert redact_text(raw) == expected


@pytest.mark.parametrize("text", INNOCENT)
def test_innocent_text_unchanged(text):
    assert redact_text(text) == text


@pytest.mark.parametrize(("raw", "_"), SECRET_CASES)
def test_idempotent(raw, _):
    once = redact_text(raw)
    assert redact_text(once) == once


def test_redact_nested_structures():
    obj = {"a": ["token=abc12345", {"b": "ok"}], "c": ("password=x1",), "n": 3}
    assert redact(obj) == {
        "a": ["token=[REDACTED]", {"b": "ok"}],
        "c": ("password=[REDACTED]",),
        "n": 3,
    }


def test_allowlists():
    assert ALLOWED_TOOLS == {
        "get_job_status",
        "search_logs",
        "query_metric",
        "search_runbooks",
        "list_recent_incidents",
        "propose_remediation",
    }
    assert ALLOWED_REMEDIATIONS == {
        "restart_job",
        "increase_memory",
        "rerun_with_backoff",
        "clear_scratch_space",
        "escalate_to_oncall",
    }


def test_truncate_result():
    assert truncate_result("short") == "short"
    out = truncate_result("x" * 20, limit=10)
    assert out == "x" * 10 + "...[truncated 10 chars]"
    assert len(truncate_result("y" * 9000)) < 9000 + 40
    assert MAX_TOOL_RESULT_CHARS == 8000
    assert DEFAULT_MAX_TURNS == 20


def _raw_log_text(scenario) -> str:
    return "\n".join(line.message for line in scenario.logs)


def test_no_fake_secret_survives_redaction_in_any_scenario():
    for sid, scenario in load_scenarios().items():
        assert "FAKE-" not in redact_text(_raw_log_text(scenario)), sid


STATUS_VALUES = [
    "token: expired",
    "token=EXPIRED.",
    "password: invalid",
    "api_key=missing",
    '"secret": "null"',
    "client_secret=revoked,",
    "authorization: denied!",
    "access_key: rotated)",
    "token=refreshed",
    "pwd: none",
    "secret=false",
]


@pytest.mark.parametrize("text", STATUS_VALUES)
def test_status_words_after_a_key_are_preserved(text):
    assert redact_text(text) == text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("password=correcthorsebatterystaple", "password=[REDACTED]"),
        ("token=expired_but_actually_a_secret", "token=[REDACTED]"),
        ("api_key=invalid1234", "api_key=[REDACTED]"),
        ("secret: s3cr3t.", "secret: [REDACTED]"),
    ],
)
def test_secret_looking_values_still_redacted(raw, expected):
    assert redact_text(raw) == expected


@pytest.mark.parametrize("text", STATUS_VALUES)
def test_status_word_redaction_is_idempotent(text):
    once = redact_text(text)
    assert redact_text(once) == once


def test_redaction_keeps_every_key_evidence_substring():
    # Redaction must never destroy evidence the evals rely on. Checked per line and on
    # the whole log, since tool results carry many lines at once.
    for sid, scenario in load_scenarios().items():
        lines = [f"{line.level} {line.component} {line.message}" for line in scenario.logs]
        redacted_whole = redact_text("\n".join(lines))
        redacted_lines = "\n".join(redact_text(line) for line in lines)
        for evidence in scenario.ground_truth.key_evidence:
            assert evidence in redacted_whole, (sid, evidence)
            assert evidence in redacted_lines, (sid, evidence)


def test_raw_auth_logs_do_contain_fake_secret():
    # Guards against a vacuous test above: the unredacted data really has fake secrets.
    assert "FAKE-" in _raw_log_text(load_scenarios()["auth_expired_01"])
