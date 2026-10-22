# Disk Full on Worker or Scratch Volume

## Symptoms
The job fails while writing, spilling, or extracting. Logs show "No space left on device", ENOSPC, "IOException: disk quota exceeded", or failed shuffle writes and checkpoint writes. Disk usage on the worker or scratch volume sits at or near 100 percent. Other jobs on the same host may start failing in the same way. The job may have been healthy for a long time until temporary files accumulated, and a retry on the same host fails at the same point.

## Diagnosis
1. Confirm the error text names a device or path, which separates a full disk from a memory problem.
2. Check the disk usage metric for the host or volume over the past day. A slow climb to 100 percent points to accumulation of temporary files. A sudden jump points to one large write.
3. List the biggest directories under the scratch path. Look for stale shuffle files, old spill data, leftover job output, and rotated logs that were never deleted.
4. Check whether earlier failed runs left partial output behind, since crashed jobs often skip their own cleanup.
5. Verify the job's own output size has not grown unexpectedly, which would need a bigger volume instead of a cleanup.

## Remediation
Clear the stale temporary and scratch data that is safe to delete, which means files from finished or dead jobs and never active data or committed outputs. Confirm the free space is back to a healthy margin, then restart or rerun the job. If space fills again quickly, schedule a regular cleanup of the scratch directory.

Platform action: `clear_scratch_space`

## Escalate when
Escalate if cleanup frees little space because the data is live, if the volume fills again within hours, if the required output is larger than the disk, or if the files cannot be proven safe to delete.

## Commonly confused with
Out of memory: both kill a job mid-run. A full disk reports an explicit device or space error, while an OOM reports heap or container memory limits and exit code 137.
Resource starvation: starvation is slowness from contention, with no hard "no space" error.
