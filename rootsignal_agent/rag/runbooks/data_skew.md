# Data Skew in Distributed Jobs

## Symptoms
One or a few tasks run far longer than the rest of their stage, or fail while the remaining tasks finish quickly. The job appears stuck at 99 percent. Stage duration is dominated by a straggler. A single executor may hit an out-of-memory error or a spill-to-disk storm while other executors sit idle. Failures reproduce on every retry, always on the same partition, and typically appear after a join, groupBy, or aggregation on a column with a few very common values such as null, "unknown", or one huge customer id.

## Diagnosis
1. Open the stage task summary and compare the maximum task duration and input size with the median. A ratio above 10x is a strong sign of skew.
2. Identify the key being shuffled and count rows per key. A handful of keys holding a large share of all rows confirms hot keys.
3. Check whether the null or default value is the hot key. Missing join keys collapsing into one partition are a very common cause.
4. Verify that overall cluster memory and CPU are healthy. Skew is a distribution problem, not a capacity one.
5. Look for what changed upstream: a new tenant, a bulk backfill, or a default value that started being written.

## Remediation
Skew needs a change in the job's logic, such as salting the hot key, enabling adaptive skew-join handling, broadcasting the small side of the join, or filtering out null keys before the join. These are code or configuration changes owned by the job's team, so the platform cannot safely fix them on its own. Collect the hot key evidence and hand it over.

Platform action: `escalate_to_oncall`

## Escalate when
Escalate immediately once skew is confirmed, because retries and extra resources will not help. Include the stage, the hot key, and the task size ratio.

## Commonly confused with
Out of memory: both end with a failed task and memory errors. Skew has one oversized task and many small ones; an ordinary OOM has uniformly high memory on every task after input grew evenly. Raising memory hides skew only briefly.
Resource starvation: starvation slows every task because the cluster is busy. Skew slows only the tasks holding the hot key, while the cluster has idle capacity.
