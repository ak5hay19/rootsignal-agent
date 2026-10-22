from typing import Any

from rootsignal_agent.sim.engine import PlatformEngine


def get_job_status(engine: PlatformEngine, job_name: str) -> dict[str, Any]:
    return engine.get_job_status(job_name)
