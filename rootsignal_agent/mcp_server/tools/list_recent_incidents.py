from typing import Any

from rootsignal_agent.sim.engine import PlatformEngine


def list_recent_incidents(engine: PlatformEngine, team: str) -> dict[str, Any]:
    incidents = engine.list_recent_incidents(team)
    result: dict[str, Any] = {"team": team, "incidents": incidents}
    if not incidents:
        result["note"] = f"No incidents found for team {team}"
    return result
