# Schema suggestions from example documents

## Product and architecture

Upload 1–5 examples, request one small reusable schema, inspect/edit it in the
existing builder, apply it to an already uploaded document, and optionally save it
to the existing private schema library. Applying a suggestion does not save it or
start a paid extraction. Extraction remains a separate action with normal evidence
verification. Built-in templates are unchanged.

The core owns discovery contracts, bounded field-plan compilation, provider
adapters and durable jobs. Cloud owns the interface, account/tenant access and
credit metering. The same worker alternates suggestion and extraction work; both
queues share database-wide job capacity and the existing model-request limiter.

1. The existing isolated reader prepares text, tables and images. This makes no
   model calls. Formats are detected from their bytes.
2. Decider selects TEXT, VISION or TEXT_AND_VISION for sampled original units.
   Only available modalities are offered. It then assesses whether all examples
   fit one compact schema, with SHARED, DIFFERENT or INSUFFICIENT outcomes.
3. Haiku proposes English labels, technical keys, types, descriptions and citations
   as a restricted field plan. The application compiles JSON Schema, checks source
   identities and validates it through the existing core normalizer. One repair
   attempt is permitted. Structured output uses an explicitly unrolled tree;
   Pydantic AI StructuredDict does not support recursive field references.
4. Decider independently checks every leaf concept against its cited original
   sources. A field may appear in only one example. Unsupported/uncertain concepts
   remain visibly marked for review; field support is not verification of future
   extracted values. No raw probability is advertised as calibrated confidence.

Default models: `perplexity/pplx-decider-v1.2` for decisions and
`anthropic/claude-haiku-5.5` for generation. Suggestions introduce no automatic
stronger-model escalation. Model settings and policy version are snapshotted on
each job. New discovery questions are independent from extraction relevance.

## Bounds, uncertainty and persistence

The field plan allows 1–10 root fields, up to 20 scalar leaves and two nested group
levels. Repeating rows become arrays of objects. Scalar identifiers and dates are
strings; all generated values permit null. No enums, instance examples, arbitrary
JSON Schema keywords or document-generated extraction instructions are copied into
the saved schema. Prompts require generic labels/descriptions without source values;
semantic compliance remains a model-quality concern, not a privacy guarantee.
Source citations, compatibility diagnostics and model decisions stay outside the
reusable `{name, schema, instructions}` envelope.

Default discovery samples up to three evenly spaced units per document, reduced
as needed to keep at most eight units across examples. This positional policy is
a mechanical resource bound, not a content-relevance decision. Every document is
represented. Inspected unit IDs, total unit counts and partial coverage are
returned explicitly. There is no claim to have reviewed unseen pages. More than
the configured image limit (including embedded DOCX images), oversized requests
or unavailable modalities fail explicitly. Large-document adaptive exploration
and automatic grouping into multiple schemas are deferred.

Discovery defaults to a USD 0.05 estimated model-spend limit, 12 physical request
attempts and the deployment's job time limit. Overrides:

- `AI_IDP_SCHEMA_SUGGESTION_MODEL`
- `SCHEMA_SUGGESTION_MAX_COST_USD`
- `SCHEMA_SUGGESTION_MAX_CALLS`
- `SCHEMA_SUGGESTION_UNITS_PER_DOCUMENT`

Spend limits are checked before additional calls and after reported/estimated
usage; they are not hard provider billing caps. Physical attempts are reserved
durably, including retries, before dispatch. Successful steps and usage are
checkpointed; renewable leases fence stale workers. A crash after a provider
response but before durable checkpoint storage may repeat that call. Cancelling
prevents further dispatch; an already sent request may still incur cost. Late
reported usage may be recorded without restoring a cancelled job to running.

Cloud enforces document ownership, suggestion owner/tenant isolation, session CSRF,
API key scopes and positive credit before submission. Idempotency keys are scoped
to the caller; unchanged retries return the same job, and conflicting requests
return 409. Browser refresh retains only owner/job identifiers in sessionStorage
and resumes polling. A new explicit analysis after a terminal result creates a
new job. Account changes clear suggestion views. Existing file retention policies
also apply to discovery artifacts; no new automatic deletion promise is made.

## API and rollout

Apply core migration `0004_schema_suggestions` with `uv run python -m alembic
upgrade head` before restarting API/worker. Cloud adds its ownership table through
the existing additive table initialization. No dependency/lockfile change is needed.

- `POST /v1/schema-suggestions`: `{document_ids: [...], max_cost_usd?: ...}`,
  optional `Idempotency-Key`, returns 202 and job status.
- `GET /v1/schema-suggestions/{job_id}`: progress, usage, model snapshot and result.
- `POST /v1/schema-suggestions/{job_id}/cancel`: cancel pending/running discovery.

Terminal outcomes are completed, needs_review, failed or cancelled. A completed
result contains the schema envelope, leaf assessments, source references, source
locators and coverage warnings. Mixed/insufficient inputs return needs_review
without inventing a generic schema. Source values are produced only by a separate
ordinary extraction job after the user applies the schema.

## Evaluation first (M0)

Before provider work, validate the unchanged 120-case corpus and define discovery
criteria separately from fixed extraction answer keys. Evaluate useful field
concepts, unsupported concepts, compactness, builder/core validity, meaningful
table structure, compatibility, edit burden, cost and latency. Measure downstream
extraction on a different example from the same development family. Exact field
names need not match a single canonical schema. Current AI source reviews are
development references, not independent human ground truth. Do not tune against
calibration/holdout or replace source identities.

Offline regressions cover normal and mixed outcomes, source sampling, citation
validation, bounded repair, unsupported-field warnings, spend/request limits,
cancelled usage, shared queue capacity, crash recovery and checkpoint reuse.
Cloud tests cover ownership, CSRF, scopes, credit gates, caller-scoped idempotency,
billing, save and subsequent extraction. An opt-in PostgreSQL regression exercises
the actual migrated schema and competing claims. No normal test calls providers.

Owner-authorized real-provider smoke tests on 2026-10-19 used only newly authored
synthetic examples, with a shared USD 0.50 guard and retained local spend journal.
Browser flow: two different PDF invoices → suggested schema → refresh recovery →
builder → private account save → real extraction and source highlight. The due-date
field, present only in the second example, correctly became null in the first.
Separate API flows exercised an image-only invoice, incompatible invoice/resume
inputs, a shared DOCX/Excel invoice schema, and reuse of the saved PDF-derived
schema on a third invoice with different values and GBP currency. All these smoke
flows passed. A final browser run also accepted a native PDF and image-only copy
as examples of one document type, with readable file/page/image source labels.
The initial provider integration exposed the recursive-schema issue
above and was corrected before generation succeeded. Combined recorded provider
cost across 52 physical requests, including those initial decision calls, was
USD 0.01030552. These are small
development smoke tests, not a general accuracy benchmark or billing guarantee.

External originals, generated QA documents, accounts, databases, provider responses,
screenshots and spend journals remain in ignored local evaluation storage.
