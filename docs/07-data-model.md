# 07 — PostgreSQL Data Model and Durability

Use PostgreSQL as the only database and initial work queue. Use SQLAlchemy migrations through Alembic. Avoid adding Redis or Celery prematurely.

## Initial tables

| Table | Main fields |
|---|---|
| documents | id, checksum, filename, media_type, bytes, storage_key, status, created_at |
| document_units | id, document_id, ordinal, kind, locator_json, text_ref, image_ref, metadata_json |
| extraction_specs | id, schema_json, schema_hash, instructions, created_at |
| extraction_jobs | id, document_id, spec_id, status, stage, configuration_json, progress_json, created_at, updated_at |
| job_queue | job_id, status, available_at, lease_owner, lease_until, attempt_count, heartbeat_at, last_error |
| decisions | id, job_id, unit_id?, field_path?, kind, model_id, version, scores_json, selected_json, latency_ms |
| field_attempts | id, job_id, field_path, attempt_number, candidate_json, model_id, status, error, created_at |
| field_results | job_id, field_path, final_value_json, verification_status, score_json, sources_json, unresolved_reason |
| usage_records | id, job_id, stage, model_id, tokens_in, tokens_out, estimated_cost_usd, latency_ms |
| job_steps | job_id, step_key, payload_json (completed model output) |
| evaluation_runs | id, dataset_ref, config_hash, status, metrics_json, created_at |

Store potentially large payloads (originals, rendered pages, text artifacts) in DocumentBlobStore rather than PostgreSQL JSONB. PostgreSQL stores references plus bounded metadata.

## Queue design

Worker claims a ready job in a short transaction using SELECT ... FOR UPDATE SKIP LOCKED, marks it leased, and commits. Actual model inference runs **outside the database transaction**. Heartbeat renews the lease. On completion, the worker writes final outputs idempotently and marks the job complete.

When a worker crashes, an expired lease makes the job eligible for recovery. Use a bounded number of attempts with exponential backoff. Job checkpoints avoid needlessly repeating already completed expensive stages when their inputs/configuration are unchanged.

Each execution has a unique lease owner token, including inline and evaluation execution. Every job/decision/checkpoint/result write locks and validates the same queue row inside its transaction; stale owners cannot overwrite a reclaimed execution. A lost heartbeat cancels active processing. Cancellation invalidates ownership using the same queue-first lock order.

Completed model outputs and their usage are committed atomically in `job_steps` and `usage_records`. Replay uses these outputs, reconstructs orchestration state, and records candidates idempotently without overwriting earlier values. All persisted usage contributes to the job budget, and budget exhaustion is not retried. A provider response lost before checkpoint commit can still be repeated; no exactly-once external-call guarantee is claimed.

Constraints:

- Unique extraction-job IDs and idempotency keys.
- Unique (job_id, field_path, attempt_number) for field attempts.
- Unique decision IDs / step execution IDs to survive at-least-once work execution.
- Store configuration snapshots so replays use the same effective models and policy versions.
- Separate transient provider errors from invalid inputs and nonrecoverable schema errors.
- Worker cancellation is cooperative and persisted; cancelled tasks must not finalize afterwards.

## Result semantics

A job can complete with unresolved fields. Such a result must state schema validity separately from completeness and verification status. Storing a null in an internal partial result never authorizes fabricating a value to satisfy a caller's required field.

## Persistence and future SaaS evolution

The initial data model assumes a single trusted local deployment. Do not claim multi-tenant security. If SaaS becomes a goal, add tenant ownership, row-level authorization, authenticated endpoints, encryption, quotas, retention/deletion and audit controls as explicit migrations and threat-model work.
