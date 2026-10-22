"""Simulated platform engine.

The agent-facing methods return plain JSON-serializable data and expose only what an
on-call engineer could observe. Ground truth is reachable only through
get_ground_truth_for_eval().
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from rootsignal_agent.sim.metrics import METRIC_CATALOG, build_all_series
from rootsignal_agent.sim.models import Scenario

SCENARIO_ENV_VAR = "ROOTSIGNAL_AGENT_SCENARIO"
DEFAULT_SCENARIO_DIR = Path(__file__).parent / "scenarios"


class SimError(Exception):
    """Base class for engine errors."""


class UnknownJobError(SimError):
    pass


class UnknownMetricError(SimError):
    pass


class ScenarioLoadError(SimError):
    pass


def load_scenarios(path: Path | str | None = None) -> dict[str, Scenario]:
    """Load and validate every *.yaml in `path`. Returns {scenario id: Scenario}."""
    directory = Path(path) if path else DEFAULT_SCENARIO_DIR
    scenarios: dict[str, Scenario] = {}
    for file in sorted(directory.glob("*.yaml")):
        try:
            scenario = Scenario.model_validate(yaml.safe_load(file.read_text()))
            unknown = [m.name for m in scenario.metrics if m.name not in METRIC_CATALOG]
            if unknown:
                raise ValueError(f"metrics not in METRIC_CATALOG: {unknown}")
        except (ValidationError, ValueError, yaml.YAMLError) as exc:
            raise ScenarioLoadError(f"invalid scenario file {file.name}: {exc}") from exc
        if scenario.id != file.stem:
            raise ScenarioLoadError(f"{file.name}: id '{scenario.id}' must equal filename stem")
        scenarios[scenario.id] = scenario
    return scenarios


class PlatformEngine:
    def __init__(self, scenario: Scenario) -> None:
        self._scenario = scenario
        self._series = build_all_series(scenario.metrics, scenario.as_of)

    @classmethod
    def from_dir(cls, path: Path | str | None = None, active: str | None = None) -> PlatformEngine:
        scenario_id = active or os.environ.get(SCENARIO_ENV_VAR)
        if not scenario_id:
            raise SimError(
                f"No active scenario: pass active=... or set {SCENARIO_ENV_VAR} to a scenario id"
            )
        scenarios = load_scenarios(path)
        if scenario_id not in scenarios:
            raise SimError(f"Unknown scenario '{scenario_id}'. Available: {sorted(scenarios)}")
        return cls(scenarios[scenario_id])

    # ---- helpers -------------------------------------------------------------------

    def _check_job(self, job_name: str) -> None:
        if job_name != self._scenario.job_name:
            raise UnknownJobError(
                f"Unknown job '{job_name}'. Known jobs: {[self._scenario.job_name]}"
            )

    # ---- agent-facing --------------------------------------------------------------

    def user_report(self) -> str:
        """The human's original message (the agent's input, not a tool)."""
        return self._scenario.user_report

    def get_job_status(self, job_name: str) -> dict[str, Any]:
        self._check_job(job_name)
        return self._scenario.job_state.model_dump(mode="json")

    def get_logs(
        self,
        job_name: str,
        query: str | None = None,
        limit: int = 20,
        level: str | None = None,
    ) -> list[dict[str, Any]]:
        """Most recent `limit` matching lines, oldest first. `query` is a case-insensitive
        substring match against level, component and message."""
        self._check_job(job_name)
        q = query.lower() if query else None
        matches = []
        for line in self._scenario.logs:
            if level and line.level != level.upper():
                continue
            if q and q not in f"{line.level} {line.component} {line.message}".lower():
                continue
            matches.append(line)
        recent = matches[-limit:] if limit > 0 else []
        return [line.model_dump(mode="json") for line in recent]

    def get_metric(self, name: str, job_name: str, window_minutes: int = 60) -> dict[str, Any]:
        self._check_job(job_name)
        if name not in METRIC_CATALOG:
            raise UnknownMetricError(
                f"Unknown metric '{name}'. Known metrics: {list(METRIC_CATALOG)}"
            )
        if window_minutes < 1:
            raise ValueError("window_minutes must be >= 1")
        cutoff = self._scenario.as_of - timedelta(minutes=window_minutes)
        points = [(ts, v) for ts, v in self._series[name] if ts >= cutoff]
        values = [v for _, v in points]
        return {
            "metric": name,
            "job_name": job_name,
            "unit": METRIC_CATALOG[name]["unit"],
            "window_minutes": window_minutes,
            "points": [{"ts": ts.isoformat(), "value": round(v, 4)} for ts, v in points],
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "avg": round(sum(values) / len(values), 4),
            "last": round(values[-1], 4),
        }

    def list_recent_incidents(self, team: str) -> list[dict[str, Any]]:
        if team != self._scenario.team:
            return []
        return [i.model_dump(mode="json") for i in self._scenario.recent_incidents]

    # ---- evaluation only -----------------------------------------------------------

    def get_ground_truth_for_eval(self) -> dict[str, Any]:
        """FOR EVALUATION HARNESS ONLY. Never expose through the MCP server."""
        return self._scenario.ground_truth.model_dump(mode="json")

    def as_of(self) -> datetime:
        return self._scenario.as_of
