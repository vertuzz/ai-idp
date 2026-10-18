# Operations and MVP release gates

## Deployment

This is a single trusted deployment: one API and one or more workers share PostgreSQL,
the same original/artifact storage and telemetry directory. Setting `AI_IDP_API_KEY`
enables a static shared-secret check (`Authorization: Bearer <key>` or `X-API-Key: <key>`)
on `/v1/*` endpoints while leaving `/health/*` open; multi-user authentication,
tenant isolation, billing and webhooks remain outside the MVP.

Copy `.env.example` to an ignored `.env`, set the provider credential and database
password, then run `docker compose up -d --build`. Compose waits for PostgreSQL and
the one-shot migration service before starting API and workers. Published ports bind
to loopback. The interactive API reference is available at `http://127.0.0.1:8000/docs`.

For native development, start PostgreSQL, run `uv run --locked python -m alembic upgrade head`,
then start the API and worker using the README commands. `/health/live` checks the process;
`/health/ready` checks storage and required database tables/columns. A missing migration
must not be reported as ready. No provider call is made by health checks.

## Submit and inspect an extraction

~~~text
uv run --locked python examples/extract.py eval/fixtures/synthetic/synthetic-native-01.pdf --schema examples/record.schema.json
~~~

This command submits paid model work. Upload, job submission and result retrieval are
separate HTTP operations. Reuse `document_id` to process another schema without uploading
or decoding again. Use `Idempotency-Key` only for the same document, schema, instructions
and configuration; a conflicting reuse returns 409.

`GET /v1/extractions/{id}` exposes stage, counters, usage and configuration.
`GET /v1/extractions/{id}/result` exposes data, schema errors, independent verification
states, nested JSON Pointers, evidence and candidate history. `schema_valid` describes
the data shape only; it does not certify correctness. A completed result may have
unresolved fields. Always inspect field statuses before consuming data automatically.

Decisions use `offset`/`limit` pagination. The document `units` endpoint lists stable
page/block/frame references. Its text and image endpoints and the original `content`
endpoint allow inspection of citations. These endpoints expose source material and
belong inside the same trusted access boundary as uploads and results.

## Schema support

Schema policy v2 accepts an object root with explicit properties, typed nested objects,
homogeneous arrays with an explicit item schema, enums, constants and nullable unions
with one non-null type. Required unknown values remain null in the internal partial
answer, including nested leaves; schema errors remain visible.
Missing optional non-null properties are omitted from the clean data object while their
null field diagnostics remain available.

`$ref`, dynamic references, `oneOf`, `anyOf`, `allOf`, conditional schemas,
`patternProperties`, tuple/prefix items and other explicitly rejected constructs fail
before model work. Maximum schema nesting is six, at most 100 properties per object,
and at most 256 KiB of schema JSON. This is a supported subset, not an arbitrary JSON
Schema implementation. JSON Pointer escaping follows RFC 6901 (`~0`, `~1`).

Container verification checks collection/object completeness. Each concrete leaf also
gets a separate status, citation and bounded scalar recovery. Recovered leaves are
reassembled and changed containers are checked again. Root collection recovery happens
before concrete item identities are assigned.

## Limits and recovery

The default `RELEVANCE_STRATEGY=decisions` uses the configured classifier
(`perplexity/pplx-decider-v1.2`) for one probability per source unit, considering
**all** requested fields together. `RELEVANCE_STRATEGY=generative` returns one
boolean/null flag per unit; uncertainty is retained without fabricated probabilities.
Both strategies send the complete field set in each group, with up to
`RELEVANCE_BATCH_UNITS=8` units and `MAX_DECISION_IMAGES_PER_CALL=8` images.
`MAX_DECISION_QUESTIONS_PER_CALL=24` bounds unit questions, not unit/field pairs.
A block with multiple embedded images consumes multiple image slots. Byte/image
limits may produce smaller groups; an oversized request fails without truncation.
`RELEVANCE_THRESHOLD=0.35` selects relevant units, with a document-wide
`RELEVANCE_TOP_K=2` safety floor rather than a separate floor for each field.

`MAX_PARALLEL_DECISION_BATCHES=8` bounds concurrent relevance groups and selected-unit
modality calls per job. Global/per-model capacity and pacing remain shared across
processes. A job-wide physical-attempt budget is shared by all concurrent steps and
retries, including cancelled attempts. Reported costs stop new attempts at the spend
ceiling; in-flight requests can still finish and incur charges, and cancelled calls
may have unavailable usage. Single-unit sequential comparisons set group size and
parallelism to one while preserving the full field set.

Pipeline v4 uses page-score checkpoints and `field_path=null` relevance decisions.
Pending jobs with a v3 configuration fail explicitly and must be resubmitted; completed
results remain readable. Do not reuse v3 model outputs as v4 relevance decisions.

Incoming bodies are bounded before multipart parsing; file bytes are counted separately.
Accepted documents are decoded in a subprocess, monitored for elapsed time and resident
memory. The child is killed when a limit is observed; polling is not an OS-level memory
sandbox, so transient memory overshoot remains possible. Total generated artifact bytes
are bounded and child artifacts are copied into storage only after successful decoding.

Extraction groups original units by configured count and byte size. Bounded hierarchical
model calls merge their candidates and preserve original citations. The model chooses
values and item associations; code does not choose content winners or deduplicate rows.
Verification visits every source batch; absence needs support from every batch, and
contradictions prevent acceptance. Cross-batch values that cannot be fully supported
remain unresolved. No source text is silently truncated. A single oversized unit or a
merge that cannot fit fails explicitly. Byte limits do not guarantee provider token limits.
Verification batches also respect `MAX_DECISION_IMAGES_PER_CALL` (default eight, confirmed
with the configured decision model in development). Count every embedded image, not just
document units. A single unit above that limit fails explicitly. Configure this capability
limit when changing models; image limits vary by provider, as documented in the
[OpenRouter multimodal guide](https://openrouter.ai/docs/guides/community/multimodal-decisions).

Unsupported DOCX embedded formats such as EMF remain stored as original artifacts but are
not sent as mislabeled PNG inputs. Document warnings and unit metadata expose this missing
capability. Global absence cannot be verified while such source images are unavailable.

PostgreSQL coordinates active jobs and provider request concurrency across API/worker
processes. Model pacing applies to each actual HTTP attempt, including SDK retries.
Use consistent limit settings across processes. Request leases expire after crashed
clients; job leases are renewed by heartbeat and stale owners cannot finalize results.
Do not put network calls inside database transactions.

Job deadlines start at first execution and include retry delays. Completed model steps
are replayed from durable checkpoints. Physical request budgets include recorded failed
requests and SDK retries; an interrupted request whose accounting was never committed
may still be repeated. Costs prefer provider-reported usage where available and otherwise
use estimates. Unknown failed-call billing cannot be reconstructed reliably; the configured
spend budget is not a provider-side billing cap. A response lost before checkpointing can
also be charged again. Configure provider account/key limits when a billing cap is needed.

Permanent provider rejections, resource limits and exhausted budgets are terminal.
Transient provider/network failures are retried with bounded backoff. SIGINT/SIGTERM
requests a bounded graceful worker shutdown; unfinished jobs recover after their leases
expire. Never delete a queue row to retry work manually.

## Telemetry and storage maintenance

Telemetry uses separate `spans-{process_id}.jsonl` files so processes do not rotate each
other's active files. Rotation size and archived-file retention are configurable.
Exception exports include error categories, not raw messages, tracebacks or provider
responses. Old active files left by stopped processes can be removed during maintenance.

Original documents, derived artifacts, model checkpoints and results contain document
data. Keep the data directory and PostgreSQL on restricted storage. Automatic document
deletion is not enabled. For retention maintenance, stop API/workers, back up, and remove
the selected document's database records and associated originals/artifact directory as
one controlled maintenance operation. Do not delete files while jobs are running.

## Backup, restore and upgrades

Stop API and workers before a consistent backup. Back up PostgreSQL using `pg_dump` in
custom format and copy the data directory from the same stopped deployment. Preserve
the deployed code/lockfile version and configuration securely; keep credentials outside
the backup's public metadata. Telemetry is optional for recovery. A database-only backup
cannot restore original or rendered source files.

To restore, create an empty PostgreSQL database, restore with `pg_restore`, restore the
matching data directory, apply migrations for the chosen code version, then start API
and workers. Check readiness, inspect existing document units, and exercise an extraction
on a project-owned synthetic document. Budget real model calls explicitly. Rehearse this
procedure on an isolated development deployment before relying on a backup.

Before upgrading, stop workers and API, take the consistent backup, update code and
`uv.lock`, run migrations, then restart. Schema changes in this release are additive.
Roll back with the matching database/data backup and prior code version; do not assume
older workers can execute newer pipeline checkpoints.

## Evaluation and human review

The owner accepted AI source review for local MVP assessment. All 120 reference sets have
been checked by Codex and remain explicitly marked `ai_reviewed`, not human-approved.
Use `--allow-draft` for development diagnostics; the report records reference review statuses.
The normal reviewed-benchmark guard remains unchanged. No calibration/holdout service runs
were authorized by the annotation-only permission. See [AI review scope](15-ai-source-review.md).

To record a source review that has actually been performed by an AI reviewer, use
`scripts.review_corpus record-ai-review --case-id CASE_ID --input REVIEW.json` under
`uv run --locked --group evaluation python -m`. The input must identify AI provenance,
review notes and the exact source hash. It writes local ignored output and preserves human,
rights and group approval gates. It does not inspect the document on behalf of the reviewer.

~~~text
uv run --locked --group evaluation python -m scripts.validate_corpus
uv run --locked --group evaluation python -m scripts.review_corpus prepare
uv run --locked python -m ai_idp.evaluation.runner --live --allow-draft --max-total-cost-usd 0.50 --case-id synthetic-native-01 --limit 1 --profile default --profile always_vision
~~~

Draft mode is limited to development cases and labels its reports as diagnostics.
Benchmark mode accepts only reviewed cases. Every suite has an explicit estimated budget,
source/annotation fingerprints, configuration snapshots, failures and JSON/CSV/Markdown
reports in ignored `eval/results/`. Failed examples remain in measured outcomes. Reports
include routing recall/precision, field accuracy, verification confusion, recovery,
source/format breakdowns, cost and end-to-end p50/p95 timing. Small samples do not establish
general accuracy or calibrated confidence.

Use `--unbatched-questions` to compare single-question relevance calls with question
batching; each question group has a durable checkpoint. Alternative model IDs are set
through the documented environment settings and recorded in the configuration snapshot.

Model-assisted draft authoring defaults to development with
`python -m scripts.draft_corpus_annotations --live --max-total-cost-usd AMOUNT`
under `uv run --locked --group evaluation`. Protected splits require a separately authorized
`--split calibration --split holdout --annotation-only` run. This authors drafts only;
it never evaluates the service, tunes prompts, approves labels or overwrites existing content.
Do not inspect protected answers to change extraction policies. Draft answer bytes
remain ignored and must be backed up locally; a clean source checkout does not contain
these model outputs. Repeat authoring only with an explicit new budget if they are lost.

The ignored review index is `eval/cache/human-review/index.md`. For each case a human must
inspect the original, author/correct the schema, check all expected values and citations,
and complete file-specific rights/privacy and split-group review. Record an actual review:

~~~text
uv run --locked --group evaluation python -m scripts.review_corpus record-review --case-id CASE_ID --input eval/cache/human-review/CASE_ID.json --reviewer REVIEWER_ID --rights-reviewed --groups-reviewed
~~~

The command is a record of a human decision, not an automatic approval. Use a stable
reviewer ID without personal contact details. It validates reference values and source
identity, writes project-owned reviewed annotations, and updates manifest references.
Inspect the diff, regenerate the catalog and run `validate_corpus --require-ready` before
freezing the complete benchmark. Do not tune on calibration/holdout examples.

## Release gates

Engineering checks: locked dependency sync, full offline tests, isolated PostgreSQL
concurrency/recovery tests, lint/format checks, domain/port type checks, API smoke tests,
and opt-in budgeted development model runs. CI configures Windows, Linux and macOS;
configuration alone is not evidence that a remote CI run passed.

Research acceptance remains open until all 120 annotations, rights and groups are reviewed,
the 72/24/24 split is frozen, and the measured comparison is run on that benchmark.
Do not mark M0 or the benchmark part of M6 complete merely because backend tests pass.

Before any public commit/release, run worktree and index publication checks and a secret
scan. Inspect staged paths and binary metadata. Do not publish source originals, review
drafts, model outputs, caches, local paths or credentials.
