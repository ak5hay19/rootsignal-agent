"""DRY RUN ONLY. Nothing in this module (or anywhere in the repo) executes a remediation:
it validates the request and returns a description of what would happen."""

from typing import Any

from rootsignal_agent.agent.guardrails import ALLOWED_REMEDIATIONS
from rootsignal_agent.sim.engine import PlatformEngine

# One sentence per allowlisted action. Kept in sync with the allowlist by a test.
ACTION_EFFECTS: dict[str, str] = {
    "restart_job": "Would restart the job from its first stage with its current configuration.",
    "increase_memory": "Would raise the job's executor memory allocation and rerun it.",
    "rerun_with_backoff": "Would rerun the job with exponential backoff between retry attempts.",
    "clear_scratch_space": "Would delete temporary files from the job's worker scratch disks.",
    "escalate_to_oncall": "Would page the on-call engineer with this job and the stated reason.",
}


def propose_remediation(
    engine: PlatformEngine, action: str, job_name: str, reason: str
) -> dict[str, Any]:
    if action not in ALLOWED_REMEDIATIONS:
        raise ValueError(
            f"Action '{action}' is not allowed. Allowed actions: {sorted(ALLOWED_REMEDIATIONS)}"
        )
    engine.get_job_status(job_name)  # raises UnknownJobError for an unknown job
    if not reason or not reason.strip():
        raise ValueError("reason must not be empty: explain the evidence behind this action")
    return {
        "status": "dry_run",
        "executed": False,
        "requires_approval": True,
        "action": action,
        "job_name": job_name,
        "reason": reason,
        "would_do": ACTION_EFFECTS[action],
    }
