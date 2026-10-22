"""Cost estimates and the --all spend guard, using fake investigation results."""

import argparse

import pytest

from rootsignal_agent.agent.models import InvestigationResult
from rootsignal_agent.agent.pricing import estimate_cost_usd
from rootsignal_agent.cli import format_report, run_all
from rootsignal_agent.sim.engine import load_scenarios


def test_estimate_cost_known_models():
    assert estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(12.0)
    assert estimate_cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.6)
    assert estimate_cost_usd("claude-sonnet-5-5", 0, 0) == 0.0


def test_estimate_cost_unknown_model_is_none():
    assert estimate_cost_usd("claude-made-up", 100, 100) is None


def fake_result(input_tokens: int, output_tokens: int = 0) -> InvestigationResult:
    return InvestigationResult(
        stop_reason="error",
        report=None,
        tool_calls_used=0,
        turns=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed_s=0.1,
        trace_path="trace.jsonl",
        error_message="fake",
    )


class FakeInvestigator:
    """Stands in for Investigator: every run costs the same, and runs are counted."""

    def __init__(self, model: str, result: InvestigationResult) -> None:
        self.model = model
        self.result = result
        self.scenarios: list[str] = []

    async def investigate(self, user_report: str, scenario_id: str | None = None):
        self.scenarios.append(scenario_id)
        return self.result


def args(max_cost_usd: float) -> argparse.Namespace:
    return argparse.Namespace(json=False, max_cost_usd=max_cost_usd)


def test_footer_shows_cost_estimate():
    footer = format_report(fake_result(1_000_000, 100_000), "claude-sonnet-5-5")
    assert "cost: $3.0000 (estimate)" in footer
    assert "unknown" in format_report(fake_result(10), "claude-made-up")


async def test_all_stops_before_next_scenario_when_limit_reached(capsys):
    # 50,000 input tokens on sonnet = $0.10 per run, so the limit of $0.25 is reached
    # after the third run and the fourth must not start.
    investigator = FakeInvestigator("claude-sonnet-5-5", fake_result(50_000))
    code = await run_all(investigator, args(0.25))
    out = capsys.readouterr().out

    all_ids = sorted(load_scenarios())
    assert investigator.scenarios == all_ids[:3]
    assert "Total cost: $0.3000 (estimate)" in out
    assert "Stopped early" in out
    assert all_ids[3] in out.split("Not run")[1]
    assert code == 1


async def test_all_runs_everything_when_under_limit(capsys):
    investigator = FakeInvestigator("claude-sonnet-5-5", fake_result(1_000))
    await run_all(investigator, args(0.25))
    out = capsys.readouterr().out

    assert investigator.scenarios == sorted(load_scenarios())
    assert "Stopped early" not in out
    assert "Total cost:" in out


async def test_all_with_unpriced_model_runs_everything_and_reports_unknown(capsys):
    investigator = FakeInvestigator("claude-made-up", fake_result(50_000_000))
    await run_all(investigator, args(0.25))
    out = capsys.readouterr().out

    assert investigator.scenarios == sorted(load_scenarios())
    assert "Total cost: unknown" in out
