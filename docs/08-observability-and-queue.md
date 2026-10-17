# 08 — Operations, Telemetry, and Resource Limits

## Worker topology

Run an HTTP API process and a separate worker process against the same PostgreSQL instance. Initially one worker deployment with two concurrently active document jobs and a global semaphore of six in-flight model requests. Expose per-model concurrency/rate limits as configuration.

The queue is PostgreSQL-backed with SKIP LOCKED leases and heartbeat/reclaim semantics, detailed in [the data model](07-data-model.md). Do not hold row locks during network calls.

## OpenTelemetry

Use the OpenTelemetry Python SDK to create spans for:

- HTTP request, file ingestion and unit preparation.
- Per-unit relevance, modality selection, extraction grouping.
- Field verification, escalation, coverage review.
- Database lease/checkpoint operations.
- Evaluation case/run.

Attributes: trace_id, job_id, document_id, stage, unit ID, field path, model identifier, prompt version, elapsed time, token usage, estimated cost, retry count, outcome. Use bounded attribute cardinality and avoid leaking document text.

Export locally to rotating JSONL output. Evaluate the current OpenTelemetry file-exporter package at implementation time; a small SDK-compatible JSONL span exporter is an acceptable fallback if official exporter capabilities differ across releases. Do not require Logfire or an external telemetry service for the MVP.

**Privacy defaults:** spans and logs do not contain full original documents, rendered page bytes, model API keys, raw prompts or full model responses. Rich debug payloads require explicit opt-in and secure local storage, never automatic public artifacts.

## Defaults (configurable, not permanent guarantees)

| Control | Initial default |
|---|---|
| Active document jobs | 2 |
| Concurrent model requests | 6 |
| Transient network/provider retries | 3 |
| Additional field extraction attempts | 2 |
| Missing-field coverage reviews | 1 |
| Upload size | 200 MiB |
| PDF pages / DOCX blocks | 1,000 / 1,000 |
| Estimated spend ceiling per job | USD 10 |
| Max decision/extraction wall time | stage-specific, configurable |
| Worker lease | configurable and renewed by heartbeat |
| Telemetry file size/retention | configurable rotation and retention |

Costs are estimates based on observed token usage and configured price schedules. Image billing and provider-specific accounting require validation. Do not misrepresent estimated spend as invoice-accurate.

## Failure management

- Distinguish bad input, model context overflow, schema violation, rate limit, provider outage, storage failure, worker crash and budget exhaustion.
- Retry safe transient errors with jitter/backoff; do not blindly retry invalid input.
- Surface partial/unresolved state when a bounded escalation fails.
- Record an event whenever a threshold, budget or capability limitation affects routing.
- Provide readiness checks for PostgreSQL and local storage; liveness must not depend on an external LLM provider.
- Apply bounded timeouts to PDF/image conversion and request processing.

## Metrics

Per-model and per-stage latency p50/p95, error rate, calls, tokens and spend; relevance recall from evaluation; selected-vs-processed units; escalation rate, missing-field recovery rate; throughput, queue depth, lease expirations and failures.

A local JSONL pipeline is intended for inspection now and future ingestion by standard observability tooling.
