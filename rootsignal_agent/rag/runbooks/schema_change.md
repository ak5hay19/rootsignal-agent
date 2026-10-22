# Upstream Schema Change

## Symptoms
The job reads its input but fails while parsing or transforming it. Logs show "column not found", "cannot resolve column", AnalysisException, KeyError on a field name, "type mismatch", or "cannot cast string to integer". The failure begins on a specific date and affects every run since, with the input files present and the right size. Code and credentials are unchanged, and the error always names the same field.

## Diagnosis
1. Read the error for the field name and type involved. Note whether a column is missing, renamed, or has a new data type.
2. Compare the schema of the latest input partition with that of a partition from before the failure. Differences in column names, order, nullability, or types are the root cause.
3. Check the upstream team's change log or deployment history for a release around the first failing date.
4. Confirm that the input is complete. Row counts near normal with a different structure rule out late or missing data.
5. Check whether other consumers of the same dataset are failing too, which would confirm a producer-side change.

## Remediation
Fixing this means updating the job's schema mapping or agreeing with the producer to revert or version the change. Both decisions belong to the humans who own the contract between the two teams. Retrying or adding resources does nothing because the same bad structure will be read each time. Document the old and new schema and pass them on.

Platform action: `escalate_to_oncall`

## Escalate when
Escalate as soon as a structural difference is confirmed. Raise urgency if several downstream jobs depend on the same dataset or if the change silently alters values, such as a changed unit, which is worse than a loud failure.

## Commonly confused with
Upstream late: when data arrives late the files are absent or empty. In a schema change the files exist, have normal volume, and fail only on parsing a particular field.
Auth expired: authentication errors occur before any data is read, while schema errors occur after the data has been read successfully.
Data skew: skew fails on volume of one key, never on a missing or renamed field.
