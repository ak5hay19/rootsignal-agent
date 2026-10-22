import json
import re

import pytest

from rootsignal_agent.sim.engine import (
    PlatformEngine,
    SimError,
    UnknownJobError,
    UnknownMetricError,
    load_scenarios,
)
from rootsignal_agent.sim.metrics import METRIC_CATALOG

SCENARIOS = load_scenarios()
IDS = list(SCENARIOS)


def engine_for(scenario_id: str) -> PlatformEngine:
    return PlatformEngine(SCENARIOS[scenario_id])


@pytest.fixture
def oom() -> PlatformEngine:
    return PlatformEngine.from_dir(active="oom_01")


def test_active_scenario_from_env(monkeypatch):
    monkeypatch.setenv("ROOTSIGNAL_AGENT_SCENARIO", "oom_01")
    assert PlatformEngine.from_dir().get_job_status("daily_orders")["job_name"] == "daily_orders"


def test_no_active_scenario_raises(monkeypatch):
    monkeypatch.delenv("ROOTSIGNAL_AGENT_SCENARIO", raising=False)
    with pytest.raises(SimError, match="ROOTSIGNAL_AGENT_SCENARIO"):
        PlatformEngine.from_dir()


def test_unknown_scenario_raises():
    with pytest.raises(SimError, match="nope"):
        PlatformEngine.from_dir(active="nope")


def test_logs_query_is_case_insensitive_and_chronological(oom):
    lower = oom.get_logs("daily_orders", "outofmemoryerror")
    upper = oom.get_logs("daily_orders", "OUTOFMEMORYERROR")
    assert lower and lower == upper
    stamps = [line["ts"] for line in oom.get_logs("daily_orders", limit=50)]
    assert stamps == sorted(stamps)


def test_logs_level_filter_and_limit(oom):
    errors = oom.get_logs("daily_orders", level="ERROR", limit=50)
    assert errors and all(line["level"] == "ERROR" for line in errors)
    assert len(oom.get_logs("daily_orders", limit=3)) == 3
    # limit keeps the MOST RECENT matches
    all_lines = oom.get_logs("daily_orders", limit=100)
    assert oom.get_logs("daily_orders", limit=3) == all_lines[-3:]


def test_logs_query_matches_component_and_level(oom):
    assert all(
        line["component"] == "scheduler" for line in oom.get_logs("daily_orders", "scheduler")
    )
    assert oom.get_logs("daily_orders", "warn")


def test_unknown_job_and_metric(oom):
    for call in (
        lambda: oom.get_job_status("nope"),
        lambda: oom.get_logs("nope"),
        lambda: oom.get_metric("gc_time_ratio", "nope"),
    ):
        with pytest.raises(UnknownJobError):
            call()
    with pytest.raises(UnknownMetricError, match="gc_time_ratio"):
        oom.get_metric("made_up_metric", "daily_orders")


def test_metric_window(oom):
    hour = oom.get_metric("executor_memory_utilization", "daily_orders", 60)
    day = oom.get_metric("executor_memory_utilization", "daily_orders", 1000)
    assert len(hour["points"]) == 13  # 60 min at 5 min resolution, both ends inclusive
    assert len(day["points"]) == 73  # capped by the 6 hour lookback
    assert hour["points"][-1]["ts"] == "2026-10-15T03:05:00"
    assert hour["unit"] == "ratio"
    with pytest.raises(ValueError):
        oom.get_metric("gc_time_ratio", "daily_orders", 0)


def test_metric_shows_the_story(oom):
    mem = oom.get_metric("executor_memory_utilization", "daily_orders", 360)
    assert mem["max"] > 0.9 and mem["min"] < 0.65


def test_determinism(oom):
    first = oom.get_metric("gc_time_ratio", "daily_orders", 360)
    assert first == oom.get_metric("gc_time_ratio", "daily_orders", 360)
    fresh = PlatformEngine.from_dir(active="oom_01")
    assert first == fresh.get_metric("gc_time_ratio", "daily_orders", 360)


@pytest.mark.parametrize("scenario_id", IDS)
def test_every_scenario_exposes_every_catalog_metric(scenario_id):
    scenario = SCENARIOS[scenario_id]
    engine = engine_for(scenario_id)
    for name in METRIC_CATALOG:
        result = engine.get_metric(name, scenario.job_name, 360)
        assert len(result["points"]) == 73


@pytest.mark.parametrize("scenario_id", IDS)
def test_error_logs_non_empty(scenario_id):
    """The plan's Done-when check."""
    assert engine_for(scenario_id).get_logs(SCENARIOS[scenario_id].job_name, "error")


@pytest.mark.parametrize("scenario_id", IDS)
def test_no_ground_truth_leakage(scenario_id):
    scenario, engine = SCENARIOS[scenario_id], engine_for(scenario_id)
    job = scenario.job_name
    payload = json.dumps(
        [
            engine.get_job_status(job),
            engine.get_logs(job, limit=100),
            [engine.get_metric(name, job, 360) for name in METRIC_CATALOG],
            engine.list_recent_incidents(scenario.team),
        ]
    )
    gt = scenario.ground_truth
    assert "ground_truth" not in payload
    assert gt.root_cause_detail not in payload
    assert gt.correct_runbook not in payload
    assert not re.search(rf"\b{gt.root_cause_category.value}\b", payload)


def test_wrong_team_has_no_incidents(oom):
    assert oom.list_recent_incidents("growth-ml") == []
    assert len(oom.list_recent_incidents("orders-analytics")) >= 2


def test_ground_truth_only_via_eval_method(oom):
    assert oom.get_ground_truth_for_eval()["correct_runbook"] == "oom.md"


def test_some_report_omits_job_name_but_incidents_reveal_it():
    hidden = [s for s in SCENARIOS.values() if s.job_name not in s.user_report]
    assert len(hidden) == 2
    for s in hidden:
        incidents = engine_for(s.id).list_recent_incidents(s.team)
        assert any(i["job_name"] == s.job_name and i["status"] == "failed" for i in incidents)
