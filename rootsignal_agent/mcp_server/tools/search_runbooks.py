from typing import Any

from rootsignal_agent.rag.index import RunbookIndex

MAX_RESULTS = 3


def search_runbooks(index: RunbookIndex, query: str) -> dict[str, Any]:
    results = index.search(query, k=MAX_RESULTS)
    return {
        "query": query,
        "results": [
            {
                "runbook": r["runbook"],
                "title": r["title"],
                "section": r["section"],
                "text": r["text"],
                "score": round(r["score"], 3),
            }
            for r in results
        ],
    }
