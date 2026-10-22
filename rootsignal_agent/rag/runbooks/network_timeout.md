# Network Timeouts and Connection Failures

## Symptoms
The job fails when talking to a remote service such as a database, API, or object store. Logs show "connection timed out", "read timeout", "Connection reset by peer", "No route to host", "Temporary failure in name resolution", or HTTP 502 and 504 errors. Failures are often intermittent, and the same call may succeed on a retry. The remote service has the data and the job holds valid credentials, but responses do not arrive in time. Other jobs calling the same endpoint around that time may show the same errors.

## Diagnosis
1. Read the error type. A timeout or reset with no response is a transport problem. A fast 401 or 403 is an authentication problem instead.
2. Check whether the failure is transient. If an immediate retry works, the cause is a brief network blip, a restarting pod, or a load balancer hiccup.
3. Test connectivity and DNS from the same host to the endpoint, and check the health dashboard of the remote service.
4. See whether other jobs hitting the same endpoint failed at the same time, which would suggest a shared network or dependency issue.
5. Confirm that the data and credentials are fine, so the problem is purely about reaching the service.

## Remediation
Transient network faults are safe to retry. Restart the job so it opens fresh connections and can pick a healthy route or replica. Check that the output is not duplicated if the job partly completed before failing. If the restart fails with the same timeout, stop retrying and look at the remote service.

Platform action: `restart_job`

## Escalate when
Escalate if the restart also times out, if the remote service reports an outage, if several unrelated jobs fail together, or if DNS or routing problems point at the platform network.

## Commonly confused with
Upstream late: with late upstream data the connection works and the data is not there yet. With a network timeout the connection itself fails, regardless of whether data exists.
Auth expired: authentication errors come back immediately from a reachable server, whereas timeouts mean no answer arrives.
Resource starvation: starvation slows local work; a network timeout is about a remote endpoint not responding.
