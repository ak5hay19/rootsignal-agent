"""Pydantic schema for simulated incident scenarios.

Every model forbids extra fields so a typo in a scenario YAML fails loudly.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RootCauseCategory(StrEnum):
    OOM = "oom"
    DATA_SKEW = "data_skew"
    UPSTREAM_LATE = "upstream_late"
    AUTH_EXPIRED = "auth_expired"
    SCHEMA_CHANGE = "schema_change"
    DISK_FULL = "disk_full"
    RESOURCE_STARVATION = "resource_starvation"
    NETWORK_TIMEOUT = "network_timeout"


class RemediationAction(StrEnum):
    """The remediation allowlist. Phase 3 guardrails reuse this enum."""

    RESTART_JOB = "restart_job"
    INCREASE_MEMORY = "increase_memory"
    RERUN_WITH_BACKOFF = "rerun_with_backoff"
    CLEAR_SCRATCH_SPACE = "clear_scratch_space"
    ESCALATE_TO_ONCALL = "escalate_to_oncall"


class JobState(Strict):
    job_name: str
    status: Literal["succeeded", "failed", "running", "skipped"]
    started_at: datetime
    ended_at: datetime | None = None
    attempt: int
    max_attempts: int
    last_success_at: datetime | None = None
    # Short observable string, e.g. "exit code 137". Never the root cause.
    exit_reason: str


class LogLine(Strict):
    ts: datetime
    level: Literal["INFO", "WARN", "ERROR"]
    component: str
    message: str


class MetricSpec(Strict):
    """Recipe for one metric series. Offsets are minutes from the window start."""

    name: str
    shape: Literal["flat", "spike", "ramp", "step"]
    baseline: float
    peak: float | None = None
    start_minute: int | None = None
    end_minute: int | None = None
    noise: float = 0.03  # fraction of the value, e.g. 0.03 = +/-3%
    seed: int

    @model_validator(mode="after")
    def _check_shape_fields(self) -> MetricSpec:
        if self.shape != "flat" and (self.peak is None or self.start_minute is None):
            raise ValueError(f"shape '{self.shape}' needs peak and start_minute")
        if self.shape in ("spike", "ramp") and self.end_minute is None:
            raise ValueError(f"shape '{self.shape}' needs end_minute")
        return self


class RecentIncident(Strict):
    job_name: str
    status: str
    finished_at: datetime
    title: str  # observable one-liner, no root cause


class GroundTruth(Strict):
    root_cause_category: RootCauseCategory
    root_cause_detail: str
    correct_runbook: str  # "<category>.md"
    correct_remediation: RemediationAction
    # Exact substrings of this scenario's logs; used by the Phase 7 hallucination check.
    key_evidence: list[str]


class Scenario(Strict):
    id: str
    team: str
    job_name: str
    user_report: str
    as_of: datetime  # the simulated "now"
    is_misleading: bool
    job_state: JobState
    logs: list[LogLine]
    metrics: list[MetricSpec]
    recent_incidents: list[RecentIncident]
    ground_truth: GroundTruth
