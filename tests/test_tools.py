import json

import pytest

from rootsignal_agent.agent.guardrails import ALLOWED_REMEDIATIONS
from rootsignal_agent.mcp_server.tools.get_job_status import get_job_status
from rootsignal_agent.mcp_server.tools.list_recent_incidents import list_recent_incidents
from rootsignal_agent.mcp_server.tools.propose_remediation import (
    ACTION_EFFECTS,
    propose_remediation,
)
from rootsignal_agent.mcp_server.tools.query_metric import query_metric
from rootsignal_agent.mcp_server.tools.search_logs import search_logs
from rootsignal_agent.mcp_server.tools.search_runbooks import search_runbooks
from rootsignal_agent.rag.index import RunbookIndex
from rootsignal_agent.sim.engine import (
    PlatformEngine,
    UnknownJobError,
    UnknownMetricError,
    load_scenarios,
)
from rootsignal_agent.sim.metrics import METRIC_CATALOG

SCENARIOS = load_scenarios()


@pytest.fixture(scope="module")
def index() -> RunbookIndex:
    return RunbookIndex.from_dir()


@pytest.fixture
def engine() -> PlatformEngine:
    return PlatformEngine(SCENARIOS["oom_01"])


JOB = SCENARIOS["oom_01"].job_name


def test_get_job_status_shape(engine):
    status = get_job_status(engine, JOB)
    assert status["job_name"] == JOB
    assert {"status", "attempt", "exit_reason"} <= status.keys()


def test_search_logs_shape_and_filters(engine):
    out = search_logs(engine, JOB, level="error")  # level is case-insensitive
    assert out["job_name"] == JOB
    assert out["count"] == len(out["lines"]) > 0
    assert all(line["level"] == "ERROR" for line in out["lines"])
    assert search_logs(engine, JOB, query="zzz-no-such-text")["count"] == 0


def test_search_logs_limit_clamped(engine):
    assert search_logs(engine, JOB, limit=0)["count"] == 1  # clamped up to 1
    assert search_logs(engine, JOB, limit=10_000)["count"] <= 100


def test_search_logs_invalid_level(engine):
    with pytest.raises(ValueError, match=r"INFO.*WARN.*ERROR"):
        search_logs(engine, JOB, level="FATAL")


def test_query_metric_shape_and_window_clamp(engine):
    out = query_metric(engine, "executor_memory_utilization", JOB, window_minutes=60)
    assert out["unit"] == "ratio" and out["points"]
    assert query_metric(engine, "gc_time_ratio", JOB, window_minutes=0)["window_minutes"] == 1
    assert query_metric(engine, "gc_time_ratio", JOB, window_minutes=9999)["window_minutes"] == 360


def test_query_metric_unknown_metric_lists_valid_names(engine):
    with pytest.raises(UnknownMetricError) as exc:
        query_metric(engine, "cpu_temperature", JOB)
    assert all(name in str(exc.value) for name in METRIC_CATALOG)


def test_unknown_job_errors(engine):
    for call in (
        lambda: get_job_status(engine, "nope"),
        lambda: search_logs(engine, "nope"),
        lambda: query_metric(engine, "gc_time_ratio", "nope"),
        lambda: propose_remediation(engine, "restart_job", "nope", "because"),
    ):
        with pytest.raises(UnknownJobError, match="daily_orders"):
            call()


def test_search_runbooks_shape(index):
    out = search_runbooks(index, "executor OutOfMemoryError java heap space exit code 137")
    assert out["query"].startswith("executor")
    assert 1 <= len(out["results"]) <= 3
    assert len({r["runbook"] for r in out["results"]}) == len(out["results"])
    first = out["results"][0]
    assert {"runbook", "title", "section", "text", "score"} == first.keys()
    assert first["score"] == round(first["score"], 3)


def test_list_recent_incidents(engine):
    team = SCENARIOS["oom_01"].team
    out = list_recent_incidents(engine, team)
    assert out["team"] == team and out["incidents"] and "note" not in out
    empty = list_recent_incidents(engine, "ghost-team")
    assert empty["incidents"] == []
    assert empty["note"] == "No incidents found for team ghost-team"


@pytest.mark.parametrize("action", ["delete_job", "drop_table"])
def test_propose_rejects_non_allowlisted(engine, action):
    with pytest.raises(ValueError, match="restart_job"):
        propose_remediation(engine, action, JOB, "because")


def test_propose_requires_reason(engine):
    for reason in ("", "   "):
        with pytest.raises(ValueError, match="reason"):
            propose_remediation(engine, "restart_job", JOB, reason)


@pytest.mark.parametrize("action", sorted(ALLOWED_REMEDIATIONS))
def test_propose_accepts_allowlisted_as_dry_run(engine, action):
    out = propose_remediation(engine, action, JOB, "evidence")
    assert out["status"] == "dry_run"
    assert out["executed"] is False
    assert out["requires_approval"] is True
    assert out["would_do"] == ACTION_EFFECTS[action]


def test_action_effects_cover_exactly_the_allowlist():
    assert set(ACTION_EFFECTS) == set(ALLOWED_REMEDIATIONS)


def test_propose_has_no_side_effects(engine):
    before = json.dumps(get_job_status(engine, JOB), sort_keys=True)
    for action in ALLOWED_REMEDIATIONS:
        propose_remediation(engine, action, JOB, "evidence")
    assert json.dumps(get_job_status(engine, JOB), sort_keys=True) == before


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_no_ground_truth_leaks_through_observation_tools(scenario_id):
    scenario = SCENARIOS[scenario_id]
    engine = PlatformEngine(scenario)
    job = scenario.job_name
    outputs = [
        get_job_status(engine, job),
        search_logs(engine, job, limit=100),
        search_logs(engine, job, level="ERROR"),
        *(query_metric(engine, m, job, 360) for m in METRIC_CATALOG),
        list_recent_incidents(engine, scenario.team),
    ]
    blob = json.dumps(outputs)
    truth = scenario.ground_truth
    assert "ground_truth" not in blob
    assert truth.root_cause_detail not in blob
    assert truth.correct_runbook not in blob
