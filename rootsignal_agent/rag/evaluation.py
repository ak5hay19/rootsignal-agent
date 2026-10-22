"""Retrieval evaluation against the simulated scenarios.

Kept apart from index.py so the index itself never depends on the sim package.
Ground truth is read here for scoring only; it never feeds the agent.
"""

from dataclasses import dataclass

from rootsignal_agent.rag.index import RunbookIndex
from rootsignal_agent.sim.engine import PlatformEngine, load_scenarios


@dataclass(frozen=True)
class EvalRow:
    scenario_id: str
    expected: str
    rank_report: int | None  # 1-based rank of the expected runbook; None = miss
    rank_with_evidence: int | None
    top3_with_evidence: list[str]


def rank_of(
    index: RunbookIndex, query: str, expected: str, k: int = 3
) -> tuple[int | None, list[str]]:
    names = [r["runbook"] for r in index.search(query, k=k)]
    return (names.index(expected) + 1 if expected in names else None), names


def evaluate(index: RunbookIndex) -> list[EvalRow]:
    """Query (a): user_report alone. Query (b): user_report + first key_evidence string."""
    rows: list[EvalRow] = []
    for scenario_id, scenario in load_scenarios().items():
        engine = PlatformEngine(scenario)
        truth = engine.get_ground_truth_for_eval()
        report = engine.user_report()
        with_evidence = f"{report}\n{truth['key_evidence'][0]}"
        rank_a, _ = rank_of(index, report, truth["correct_runbook"])
        rank_b, top3 = rank_of(index, with_evidence, truth["correct_runbook"])
        rows.append(EvalRow(scenario_id, truth["correct_runbook"], rank_a, rank_b, top3))
    return rows


def hit_rate(ranks: list[int | None], at: int) -> float:
    return sum(1 for r in ranks if r is not None and r <= at) / len(ranks)
