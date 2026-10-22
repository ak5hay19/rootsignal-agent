from typing import Any

from rootsignal_agent.sim.engine import PlatformEngine

VALID_LEVELS = ("INFO", "WARN", "ERROR")
MAX_LIMIT = 100


def search_logs(
    engine: PlatformEngine,
    job_name: str,
    query: str | None = None,
    limit: int = 20,
    level: str | None = None,
) -> dict[str, Any]:
    limit = max(1, min(limit, MAX_LIMIT))
    if level is not None:
        level = level.upper()
        if level not in VALID_LEVELS:
            raise ValueError(f"Invalid level '{level}'. Valid levels: {list(VALID_LEVELS)}")
    lines = engine.get_logs(job_name, query=query, limit=limit, level=level)
    return {"job_name": job_name, "count": len(lines), "lines": lines}
