from typing import Any

from rootsignal_agent.sim.engine import PlatformEngine

MIN_WINDOW_MINUTES = 1
MAX_WINDOW_MINUTES = 360  # the simulated platform keeps 6 hours of history


def query_metric(
    engine: PlatformEngine, metric: str, job_name: str, window_minutes: int = 60
) -> dict[str, Any]:
    window_minutes = max(MIN_WINDOW_MINUTES, min(window_minutes, MAX_WINDOW_MINUTES))
    # Unknown metrics raise UnknownMetricError, whose message lists the valid names.
    return engine.get_metric(metric, job_name, window_minutes)
