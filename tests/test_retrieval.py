import pytest

from rootsignal_agent.rag.chunking import RUNBOOK_DIR
from rootsignal_agent.rag.evaluation import evaluate, hit_rate
from rootsignal_agent.rag.index import RunbookIndex
from rootsignal_agent.sim.engine import PlatformEngine, load_scenarios

FIELDS = {"runbook", "title", "section", "text", "score"}


@pytest.fixture(scope="session")
def index() -> RunbookIndex:
    return RunbookIndex.from_dir()  # session scope: the model loads once


def test_search_result_shape(index):
    results = index.search("job ran out of memory", k=3)
    assert 1 <= len(results) <= 3
    assert all(FIELDS <= r.keys() for r in results)
    names = [r["runbook"] for r in results]
    assert len(set(names)) == len(names)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_k_limits_results(index):
    assert len(index.search("disk is full", k=1)) == 1
    assert len(index.search("disk is full", k=5)) <= 5


def test_search_is_deterministic(index):
    assert index.search("credentials rejected", k=3) == index.search("credentials rejected", k=3)


def test_invalid_inputs(index):
    with pytest.raises(ValueError):
        index.search("")
    with pytest.raises(ValueError):
        index.search("   ")
    with pytest.raises(ValueError):
        index.search("something", k=0)


def test_ground_truth_runbooks_exist_on_disk():
    for scenario in load_scenarios().values():
        truth = PlatformEngine(scenario).get_ground_truth_for_eval()
        assert (RUNBOOK_DIR / truth["correct_runbook"]).exists()


def test_top3_hit_rate_with_evidence(index):
    rows = evaluate(index)
    assert len(rows) == 10
    rate = hit_rate([r.rank_with_evidence for r in rows], at=3)
    misses = [
        (r.scenario_id, r.expected, r.top3_with_evidence) for r in rows if not r.rank_with_evidence
    ]
    assert rate >= 0.8, f"hit@3 {rate:.0%}; misses: {misses}"
