"""CLI: `python -m rootsignal_agent.rag "query"` or `python -m rootsignal_agent.rag --eval`."""

import argparse
import os

from rootsignal_agent.rag.evaluation import EvalRow, evaluate, hit_rate
from rootsignal_agent.rag.index import RunbookIndex


def show_search(index: RunbookIndex, query: str) -> None:
    for i, r in enumerate(index.search(query, k=3), start=1):
        snippet = r["text"].replace("\n", " ")[:150]
        print(f"{i}. {r['runbook']} [{r['section']}] score={r['score']:.3f}")
        print(f"   {snippet}")


def fmt_rank(rank: int | None) -> str:
    return "miss" if rank is None else str(rank)


def fmt_rate(ranks: list[int | None], at: int) -> str:
    hits = sum(1 for r in ranks if r is not None and r <= at)
    return f"{hits}/{len(ranks)} ({hit_rate(ranks, at):.0%})"


def show_eval(index: RunbookIndex) -> None:
    rows: list[EvalRow] = evaluate(index)
    print(f"{'scenario':<24}{'expected runbook':<26}{'(a) report':>11}{'(b) +evidence':>15}")
    print("-" * 76)
    for r in rows:
        print(
            f"{r.scenario_id:<24}{r.expected:<26}"
            f"{fmt_rank(r.rank_report):>11}{fmt_rank(r.rank_with_evidence):>15}"
        )
    a = [r.rank_report for r in rows]
    b = [r.rank_with_evidence for r in rows]
    print("-" * 76)
    print("(a) = user_report alone, (b) = user_report + first key_evidence line")
    print(f"hit@1  (a) {fmt_rate(a, 1):<14} (b) {fmt_rate(b, 1)}")
    print(f"hit@3  (a) {fmt_rate(a, 3):<14} (b) {fmt_rate(b, 3)}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m rootsignal_agent.rag")
    parser.add_argument("query", nargs="?", help="free-text query to search runbooks for")
    parser.add_argument("--eval", action="store_true", help="measure retrieval on all scenarios")
    args = parser.parse_args()
    if not args.eval and not args.query:
        parser.error("give a query or --eval")

    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    index = RunbookIndex.from_dir()
    show_eval(index) if args.eval else show_search(index, args.query)


if __name__ == "__main__":
    main()
