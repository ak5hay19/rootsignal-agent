# General Triage for a Failed Job

## Symptoms
Use this runbook when a job has failed or looks unhealthy and no specific cause is obvious yet. Typical reports are "the pipeline didn't finish", "the dashboard is stale", or "my job failed overnight". Start here, then switch to a cause-specific runbook as soon as the evidence points to one.

## Diagnosis
1. Check the job status first. Is it failed, still running, skipped, or succeeded with bad output? Note the start time, end time, and attempt number.
2. Read the logs from the end backwards. The last error line and the first error line are usually the most informative. Record the exact message.
3. Check the metrics for the run, including memory, CPU, disk, and duration, and compare them with the previous successful runs.
4. Look at recent changes: code deploys, configuration edits, credential rotations, upstream releases, and infrastructure maintenance.
5. Check whether this is a repeat failure. Search recent incidents for the same job and team. A job that failed three nights in a row needs a root cause, not another retry.
6. Check the dependencies, both upstream producers and downstream consumers, to understand the impact.

## Remediation
Take the least risky action that matches the evidence. Never guess: only apply a fix when the logs and metrics support a specific cause. If the evidence is weak, gather more before acting. Simple transient failures can be retried once. Record what you checked and what you did.

## Escalate when
Escalate if the cause is still unclear after the checks above, if a retry fails the same way, if the failure affects several teams, or if a deadline is at risk.

## Commonly confused with
Many causes look alike at first glance. Confirm with evidence before choosing: exit code 137 and heap errors suggest memory, a single huge task suggests skew, missing input suggests late upstream data, 401 or 403 suggests credentials, and "No space left" suggests disk.
