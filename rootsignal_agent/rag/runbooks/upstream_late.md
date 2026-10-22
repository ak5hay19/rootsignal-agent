# Upstream Data Arrives Late

## Symptoms
The job starts on schedule but finds its input missing, empty, or only partially written. Logs show messages such as "input path does not exist", "no files found for partition", "0 rows read", or a sensor timing out while waiting for a dependency. The job may succeed or fail quickly, and row counts in the output are far below normal. The failure often resolves by itself when the producer eventually finishes.

## Diagnosis
1. Check the status of every upstream dependency. Look for a producer job that is still running, delayed, or failed.
2. Compare the upstream completion time today with its usual completion time. A producer finishing later than the consumer's start time is the classic pattern.
3. Inspect the input location. Is the partition for today absent, or present but with a partial row count or a missing success marker file?
4. Confirm the consumer itself is healthy: no errors in its own code, memory normal, credentials working. The consumer is behaving correctly on bad input.
5. Check recent incidents for the upstream team, such as a slow source database or a held-up export.

## Remediation
Do not change the consumer's code. Wait for the upstream job to finish and mark its output complete, then rerun the consumer. When the completion time is uncertain, rerun with exponential backoff so the job retries after increasing delays instead of hammering a missing input. If the upstream stays broken, notify its owners.

Platform action: `rerun_with_backoff`

## Escalate when
Escalate if the upstream job has failed outright rather than being slow, if the delay threatens a downstream deadline such as a morning report, or if the same producer is late for several days in a row.

## Commonly confused with
Network timeout: a timeout also stops a job from reading data, but the log shows connection errors, resets, or unreachable hosts, and the input data exists. With late upstream data, connections work fine and the data is simply not there yet.
Schema change: a schema change has data present but unreadable columns; late data has missing or empty input.
