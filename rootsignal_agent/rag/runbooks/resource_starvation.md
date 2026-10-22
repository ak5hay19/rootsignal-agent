# Resource Starvation and Cluster Contention

## Symptoms
The job runs far slower than usual or sits queued without starting. Logs show "waiting for resources", "pending: insufficient cpu", executors lost, heartbeat timeouts, or tasks taking several times their normal duration. CPU on the node is saturated or the scheduler queue is long. There is no crash in the job's own code, no bad data, and no authentication error. Runs often complete later, or fail only because they exceed a deadline or time limit. The slowdown tracks the time of day, usually when many batch jobs start together.

## Diagnosis
1. Check the job state. Pending or queued for a long time suggests it never received its share of the cluster.
2. Look at CPU, load, and scheduler queue metrics for the cluster during the window. Sustained saturation confirms contention.
3. Identify the competing workloads. A large backfill, an ad hoc query, or many jobs scheduled on the hour will crowd out the others.
4. Compare the task duration with the usual one. Evenly slower tasks across the board indicate shared resource pressure, not one hot partition.
5. Make sure memory use is normal and no process was killed. Starvation slows work but does not terminate it with memory errors.

## Remediation
The pressure is temporary, so do not change the job. Rerun it with exponential backoff, which spaces retries out and lets the competing load drain. Where possible, move the job off the congested time slot. If the job repeatedly collides with the same neighbours, ask the platform team to adjust quotas or priorities.

Platform action: `rerun_with_backoff`

## Escalate when
Escalate if contention persists beyond the usual peak window, if the job misses a critical deadline, if a runaway workload is monopolising the cluster, or if the queue is stuck rather than slow.

## Commonly confused with
Data skew: skew slows only the tasks holding a hot key while the cluster has idle capacity. Starvation slows all tasks evenly and the cluster is busy.
Out of memory: an OOM kills the process with a memory error; starvation only delays it.
Network timeout: timeouts show failed connections, while starvation shows slow local progress.
