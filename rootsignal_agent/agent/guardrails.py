"""Guardrails: allowlists, limits, and secret redaction.

Pure Python on purpose (no mcp/anthropic/torch imports) so it loads instantly and can be
reused by both the MCP server (redaction point) and the Phase 3b agent loop (limits).
"""

from __future__ import annotations

import re
from typing import Any

from rootsignal_agent.sim.models import RemediationAction

# The only tools that may exist on the server. A test asserts the server exposes exactly these.
ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "get_job_status",
        "search_logs",
        "query_metric",
        "search_runbooks",
        "list_recent_incidents",
        "propose_remediation",
    }
)

# The only remediation actions propose_remediation will even describe (dry run).
ALLOWED_REMEDIATIONS: frozenset[str] = frozenset(a.value for a in RemediationAction)

DEFAULT_MAX_TOOL_CALLS = 10
DEFAULT_MAX_TURNS = 20  # model calls per investigation, a backstop behind the tool budget
DEFAULT_INVESTIGATION_TIMEOUT_S = 120
DEFAULT_TOOL_TIMEOUT_S = 30
MAX_TOOL_RESULT_CHARS = 8000

REDACTED = "[REDACTED]"

# ---- redaction ---------------------------------------------------------------------
# Design: every pattern captures a PREFIX (kept) and matches the secret VALUE (replaced),
# so the key name survives and the log stays readable. A key word alone ("token expired")
# is never a secret: key/value patterns require a separator (= or :) followed by a value.
# This is a best-effort defense, not a guarantee: a secret in an unknown format, or one
# split across lines, will not be caught. It is one layer next to the read-only tools.

_KEYS = r"api[_-]?key|client[_-]?secret|secret|passw(?:or)?d|pwd|token|access[_-]?key|authorization"
# prefix: optional opening quote, key, optional closing quote, separator (= or :), optional
# whitespace and opening quote. Value: a run of non-space, non-quote, non-comma characters.
_KEY_VALUE = re.compile(
    rf"""(?P<prefix>(?P<q1>["']?)\b(?:{_KEYS})(?P=q1)\s*[=:]\s*["']?)(?P<value>(?:(?:Basic|Digest)\s+)?[^\s"',;]+)""",
    re.IGNORECASE,
)
# "Bearer <token>" (also covers "Authorization: Bearer <token>"); the token needs 8+ chars
# so prose like "bearer of bad news" is left alone.
_BEARER = re.compile(r"(?P<prefix>\bBearer\s+)(?P<value>[A-Za-z0-9._~+/=-]{8,})", re.IGNORECASE)
_AWS_KEY_ID = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_GITHUB_TOKEN = re.compile(r"\bghp_[A-Za-z0-9]{36,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
)


def _keep_prefix(match: re.Match[str]) -> str:
    # Idempotence: an already-redacted value is replaced by the same marker.
    return match.group("prefix") + REDACTED


def redact_text(text: str) -> str:
    """Replace secret values in `text` with [REDACTED], keeping key names."""
    # Whole-token patterns first, then key/value ones.
    text = _PEM.sub(REDACTED, text)
    text = _JWT.sub(REDACTED, text)
    text = _AWS_KEY_ID.sub(REDACTED, text)
    text = _GITHUB_TOKEN.sub(REDACTED, text)
    # "Authorization: Bearer abc" -> the bearer rule must see the token, so run it before
    # the generic key/value rule (which would otherwise redact just the word "Bearer").
    text = _BEARER.sub(_keep_prefix, text)
    return _KEY_VALUE.sub(_redact_key_value, text)


# Values after a key that describe a state rather than hold a secret. "token: expired" is
# diagnostic evidence the agent needs, so these are kept. Anything else is still redacted.
_STATUS_WORDS: frozenset[str] = frozenset(
    {
        "expired",
        "invalid",
        "missing",
        "null",
        "none",
        "empty",
        "revoked",
        "denied",
        "rejected",
        "unauthorized",
        "forbidden",
        "required",
        "rotated",
        "refreshed",
        "valid",
        "absent",
        "unknown",
        "failed",
        "error",
        "true",
        "false",
    }
)
_TRAILING_PUNCTUATION = ".!?:)]}"


def _redact_key_value(match: re.Match[str]) -> str:
    value = match.group("value")
    # "Authorization: Bearer [REDACTED]" has the value "Bearer" here; leave it, the
    # bearer rule already handled the token after it.
    if value.lower() == "bearer":
        return match.group(0)
    # "token: expired." -> the value is "expired." -> a status word, not a secret.
    if value.rstrip(_TRAILING_PUNCTUATION).lower() in _STATUS_WORDS:
        return match.group(0)
    return _keep_prefix(match)


def redact(obj: Any) -> Any:
    """Recursively redact strings inside dicts, lists and tuples. Same structure back."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact(v) for v in obj)
    return obj


def truncate_result(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Cut `text` to `limit` characters and say how much was dropped."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[truncated {len(text) - limit} chars]"
