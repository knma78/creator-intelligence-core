# Local Persistent Job System

The Web UI uses a local SQLite task queue instead of one daemon thread per
request.

## Storage

The default database is:

```text
cache/jobs/jobs.sqlite3
```

It contains:

- `jobs`: current task state, payload, result, timestamps, worker, and attempt
  count.
- `job_events`: append-only task creation, log, claim, status, and recovery
  events.

The existing job JSON shape remains compatible. Additional fields include
`created_at`, `started_at`, `finished_at`, `worker_id`, and `attempt_count`.

## Execution

`JOB_WORKER_COUNT` controls the fixed number of local workers. The default is
one because video transcription and visual inference can use the same GPU.

Workers atomically claim the oldest queued job from SQLite. New HTTP requests
only create a durable queued record and wake a worker; they do not create a
dedicated execution thread.

## Restart recovery

On Web UI startup:

1. Jobs left in `running` state are changed back to `queued`.
2. A recovery event and visible log entry are recorded.
3. Workers execute the job again from its normal entry point.
4. Existing media, transcript, and analysis caches provide stage-level reuse.

This is task restart recovery, not instruction-level continuation. A pipeline
stage that has no reusable artifact may run again.

## Configuration

```env
JOB_WORKER_COUNT=1
JOB_QUEUE_CAPACITY=100
JOB_HISTORY_LIMIT=20
JOB_LOG_LIMIT=500
JOB_DB_PATH=
```

`JOB_DB_PATH` defaults to `cache/jobs/jobs.sqlite3`.

## API

- `GET /api/jobs`: recent persisted jobs.
- `GET /api/jobs/<job_id>`: current job state.
- `GET /api/jobs/<job_id>/events`: persisted task events.

The health endpoint includes queue status counts, worker count, capacity, and
the number of jobs recovered during the current startup.
