# Expired or Revoked Credentials

## Symptoms
The job fails at the first call to an external system such as a warehouse, object store, or API. Logs show 401 Unauthorized, 403 Forbidden, "Access Denied", "token has expired", "invalid credentials", or "permission denied". The job often ran successfully the day before and nothing in the code changed. The failure is immediate and deterministic, and it repeats on every retry. Resource usage is normal because the job never got far enough to do real work.

## Diagnosis
1. Read the exact status code. 401 means the identity was not accepted, often an expired token or rotated secret. 403 means the identity was accepted but is not allowed, often a revoked grant or changed policy.
2. Find the credential in use, usually a service account key, API token, or short-lived certificate, and check its expiry date.
3. Ask whether a secret rotation, access review, or IAM policy change happened recently.
4. Test the same credential from a safe shell against the failing endpoint to confirm it is rejected outside the job too.
5. Confirm the target service itself is up. A healthy service returning an authentication error points at the credential rather than at the service.

## Remediation
Renewing or rotating a credential requires access to the secret store and the approval of the credential owner. Automation must not mint or replace secrets, and restarting the job only repeats the rejected call. Hand the details to the on-call engineer who can renew the credential or restore the grant, then rerun the job once it is fixed.

Platform action: `escalate_to_oncall`

## Escalate when
Escalate as soon as an authentication error is confirmed. Include the endpoint, the status code, the identity name, and its expiry date, but never paste the secret itself.

## Commonly confused with
Network timeout: both stop the job at the first external call. A timeout produces no response, with connection resets or unreachable hosts. An auth failure produces a fast, explicit rejection from a reachable server.
Schema change: a schema problem appears after the data is read successfully; an auth problem appears before any data is read.
