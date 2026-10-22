"""The structured investigation report, and the local submit_report tool built from it.

The model fills InvestigationReport by calling submit_report; the loop validates the
tool input with pydantic, so the schema the model sees and the check we run are the same.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rootsignal_agent.agent.guardrails import ALLOWED_TOOLS
from rootsignal_agent.sim.models import RemediationAction, RootCauseCategory

MAX_QUOTE_CHARS = 200

Confidence = Literal["low", "medium", "high"]
StopReason = Literal["submitted", "budget_exhausted", "timeout", "max_turns", "error"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceItem(Strict):
    tool: str = Field(
        description="The tool whose result contains the quote.",
        # Shown to the model as an enum; the validator below enforces it.
        json_schema_extra={"enum": sorted(ALLOWED_TOOLS)},
    )
    quote: str = Field(
        max_length=MAX_QUOTE_CHARS,
        description=(
            f"A verbatim excerpt (at most {MAX_QUOTE_CHARS} characters) copied exactly from "
            "that tool's result. Never paraphrase."
        ),
    )
    why_it_matters: str = Field(description="How this excerpt supports or rules out a cause.")

    @field_validator("tool")
    @classmethod
    def _known_tool(cls, value: str) -> str:
        if value not in ALLOWED_TOOLS:
            raise ValueError(f"tool must be one of {sorted(ALLOWED_TOOLS)}")
        return value


class AlternativeConsidered(Strict):
    category: RootCauseCategory
    why_rejected: str = Field(description="The evidence that rules this cause out.")


class ProposedRemediation(Strict):
    action: RemediationAction
    rationale: str


class InvestigationReport(Strict):
    root_cause_category: RootCauseCategory | Literal["unknown"]
    summary: str = Field(description="1-3 plain sentences for the engineer who reported the issue.")
    evidence: list[EvidenceItem] = Field(min_length=1)
    alternatives_considered: list[AlternativeConsidered] = Field(min_length=1)
    runbook: str | None = Field(
        default=None,
        description="Filename of the runbook that matches the evidence (e.g. 'oom.md'), or null.",
    )
    proposed_remediation: ProposedRemediation | None = Field(
        default=None, description="The action you proposed with propose_remediation, or null."
    )
    confidence: Confidence


class InvestigationResult(Strict):
    """What investigate() returns. A report can exist even when stop_reason is
    "budget_exhausted" (the model was forced to submit after the tool budget ran out)."""

    stop_reason: StopReason
    report: InvestigationReport | None
    tool_calls_used: int
    turns: int
    input_tokens: int
    output_tokens: int
    elapsed_s: float
    trace_path: str
    error_message: str | None = None


# A LOCAL control tool: the loop handles it itself and never forwards it to the MCP
# server. It is not in ALLOWED_TOOLS and does not count against the tool budget.
SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_report",
    "description": (
        "Submit your final investigation report. Call this exactly once, at the end, after "
        "gathering evidence. Every evidence quote must be copied verbatim from a tool result. "
        "If the input is invalid you get an error back and can fix it."
    ),
    "input_schema": InvestigationReport.model_json_schema(),
}
