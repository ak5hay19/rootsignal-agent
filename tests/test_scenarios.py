import re

import pytest

from rootsignal_agent.sim.engine import ScenarioLoadError, load_scenarios
from rootsignal_agent.sim.models import RemediationAction, RootCauseCategory

SCENARIOS = load_scenarios()


def test_scenarios_load_and_ids_match_filenames():
    assert len(SCENARIOS) == 10
    # load_scenarios already enforces id == filename stem; ids are dict keys so unique.
    assert len({s.id for s in SCENARIOS.values()}) == 10


def test_all_root_cause_categories_covered():
    covered = {s.ground_truth.root_cause_category for s in SCENARIOS.values()}
    assert covered == set(RootCauseCategory)


def test_exactly_two_misleading():
    assert sum(s.is_misleading for s in SCENARIOS.values()) == 2


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=list(SCENARIOS))
class TestEachScenario:
    def test_logs_shape(self, scenario):
        assert 30 <= len(scenario.logs) <= 60
        stamps = [line.ts for line in scenario.logs]
        assert stamps == sorted(stamps)
        assert all(ts <= scenario.as_of for ts in stamps)
        assert any(line.level == "ERROR" for line in scenario.logs)

    def test_key_evidence_in_logs(self, scenario):
        text = "\n".join(line.message for line in scenario.logs)
        assert scenario.ground_truth.key_evidence
        for evidence in scenario.ground_truth.key_evidence:
            assert evidence in text

    def test_ground_truth_conventions(self, scenario):
        gt = scenario.ground_truth
        assert isinstance(gt.correct_remediation, RemediationAction)
        assert gt.correct_runbook == f"{gt.root_cause_category.value}.md"

    def test_incidents_include_own_failure(self, scenario):
        own = [i for i in scenario.recent_incidents if i.job_name == scenario.job_name]
        assert 2 <= len(scenario.recent_incidents) <= 4
        assert any(i.status == "failed" for i in own)

    def test_logs_do_not_leak_ground_truth(self, scenario):
        text = "\n".join(line.message for line in scenario.logs)
        gt = scenario.ground_truth
        assert gt.root_cause_detail not in text
        assert gt.correct_runbook not in text
        assert not re.search(rf"\b{gt.root_cause_category.value}\b", text)


def test_some_scenarios_have_repeat_failures():
    repeats = [
        s.id
        for s in SCENARIOS.values()
        if sum(i.job_name == s.job_name for i in s.recent_incidents) >= 2
    ]
    assert len(repeats) >= 2


def test_misleading_scenarios_keep_true_category():
    cats = {s.id: s.ground_truth.root_cause_category for s in SCENARIOS.values() if s.is_misleading}
    assert set(cats.values()) == {RootCauseCategory.AUTH_EXPIRED, RootCauseCategory.UPSTREAM_LATE}


def test_bad_yaml_fails_loudly_naming_file(tmp_path):
    (tmp_path / "bad_01.yaml").write_text("id: bad_01\nbogus_field: 1\n")
    with pytest.raises(ScenarioLoadError, match="bad_01.yaml"):
        load_scenarios(tmp_path)
