# Escalation Policy

## Symptoms
Apply this policy when a failure cannot be resolved safely with the standard runbooks, when it needs a human decision, or when business impact is growing. Examples include credential problems, contract changes between teams, repeated failures, and outages affecting many jobs.

## Diagnosis
Decide the severity before paging anyone.
Severity 1: a critical production pipeline is down, customer-facing data is wrong, or many teams are affected. Page the on-call engineer immediately.
Severity 2: an important job is failing and a deadline is at risk within hours. Notify the on-call engineer and the owning team's channel.
Severity 3: a single non-critical job failed, with a known workaround or no deadline. Create a ticket for the owning team and handle it during working hours.
Severity 4: informational or cosmetic issues. Log them for later review.

## Remediation
Page the platform on-call engineer for severity 1 and 2 incidents, and contact the job's owning team for anything involving its code or data. Contact the upstream team when the cause is a producer change. A good handoff is short and complete. It contains:
- the job name and the time of failure
- the exact error message
- what was checked and what was ruled out
- what actions were already taken, including retries
- the current impact and any deadline
- a link to logs, metrics, and related incidents
- your best hypothesis and how confident you are
Never include secrets or credentials in a handoff message.

## Escalate when
Move to a higher severity if the impact grows, if more jobs begin to fail, if no one acknowledges the page within the agreed time, or if a fix attempt makes things worse.

## Commonly confused with
Escalation is not a substitute for triage. Do the basic checks first so the on-call engineer receives evidence rather than a bare alert. Do not escalate problems that a safe, allowed remediation has already resolved, but do record them.
