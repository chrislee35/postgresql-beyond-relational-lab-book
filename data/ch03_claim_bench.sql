-- pgbench custom script for Chapter 3, Exercise 6.
--
-- Claims one job with the atomic FOR UPDATE SKIP LOCKED pattern, then
-- immediately releases it back to 'queued' in the same transaction. This
-- keeps the pool of claimable rows constant for the duration of the
-- benchmark run instead of draining the 45-row seed data in a few seconds,
-- so throughput numbers reflect claim contention rather than queue
-- exhaustion.
--
-- Usage:
--   pgbench -n -c 4 -j 4 -T 10 -f ch03_claim_bench.sql portsmith

BEGIN;

WITH next_job AS (
    SELECT id
    FROM   jobs
    WHERE  status = 'queued'
    ORDER  BY priority ASC, created_at ASC, id ASC
    FOR UPDATE SKIP LOCKED
    LIMIT  1
)
UPDATE jobs
SET    status       = 'in_progress',
       claimed_at   = now(),
       claimed_by   = 'bench-' || :client_id,
       heartbeat_at = now()
FROM   next_job
WHERE  jobs.id = next_job.id
RETURNING jobs.id AS claimed_id \gset

UPDATE jobs
SET    status = 'queued', claimed_at = NULL, claimed_by = NULL, heartbeat_at = NULL
WHERE  id = :claimed_id;

COMMIT;
