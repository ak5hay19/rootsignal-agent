# Out of Memory Failures

## Symptoms
The job dies abruptly, often partway through a stage, with no clean application error. Logs contain java.lang.OutOfMemoryError: Java heap space, "Container killed by YARN for exceeding memory limits", MemoryError, or an exit code 137 (SIGKILL from the kernel OOM killer). Container or process memory climbs steadily until the moment of failure. Retries fail at roughly the same point.

## Diagnosis
1. Check the exit code and last log lines. Exit code 137 or an explicit OutOfMemoryError confirms memory exhaustion rather than a logic bug.
2. Plot memory usage for the job over the failed run. A steady ramp up to the configured limit points to a plain memory shortfall.
3. Compare input size with recent successful runs. A modest, uniform growth in input volume is the usual trigger: the same code now needs more heap than was configured.
4. Look at per-task memory. If every worker is near the limit, the allocation is simply too small. If only one or two tasks are huge while the rest are idle, this is not a sizing problem (see the confusion section).
5. Check for a recent change that increased memory use, such as a new join or a larger cache.

## Remediation
Raise the memory limit for the job, typically by 50 to 100 percent, and rerun. Note the peak usage so the new limit has headroom. If memory keeps growing after the increase, suspect a leak and hand the job to its owners.

Platform action: `increase_memory`

## Escalate when
Escalate if the job still fails after one memory increase, if usage grows without bound regardless of limit (leak), if the requested memory exceeds what the cluster queue allows, or if the job is business critical and the deadline is close.

## Commonly confused with
Data skew: both show a task running out of memory. In an OOM caused by under-sizing, memory is high across all tasks and the input grew evenly. With data skew, one partition or key is far larger than the others, and a single task fails while its peers finish quickly with low memory. Adding memory to a skewed job only delays the failure.
Resource starvation: starvation shows slowness and queueing from contention with other workloads, not a killed process. If the job was never killed and is only slow, it is not an OOM.
