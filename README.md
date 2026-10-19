# AI-IDP

AI-IDP is an open-source, general-purpose Intelligent Document Processing (IDP) project. It explores **AI-directed document understanding**: a decision model selects the document content and processing modality needed for a caller-defined extraction schema, generative models extract structured values, and an independent decision model checks field-level evidence.

The project begins as a self-hosted HTTP API and may later evolve into a production service or SaaS product. It is **not specific to any industry, employer, or proprietary document workflow**.

**Status:** The self-hosted backend implements the HTTP API, durable queue, isolated document decoding, nested-field evidence/verification, bounded extraction and source-batch verification, shared model limits, request/spend/time budgets, diagnostics and evaluation reports. All 120 source files now have owner-authorized AI source reviews covering 1,024 reference fields. Development comparisons use these local AI-reviewed references; independent human benchmark approval and redistribution clearance are not claimed. See [AI review scope](docs/15-ai-source-review.md) and [operations](docs/13-operations-and-release.md).

**License:** [Apache License 2.0](LICENSE). Contributions and dependencies must be compatible with permissive open-source distribution.

## Local start

Development currently takes place on Windows; the project targets Windows, Linux and macOS.
Install uv and Docker with Compose v2.20+, start the Docker engine, then run from
the repository root:

~~~text
uv sync --locked --group dev --group evaluation
uv run --locked python scripts/dev.py up
~~~

Open `http://127.0.0.1:8000/docs`. This starts one API, one worker and an isolated
PostgreSQL database, with migrations and readiness checks. `.env` is created from
the example only if missing. Startup makes no model requests; persisted queued
work may resume. Manage the same stack with:

~~~text
uv run --locked python scripts/dev.py status
uv run --locked python scripts/dev.py logs
uv run --locked python scripts/dev.py restart
uv run --locked python scripts/dev.py down
~~~

`down` preserves database/uploads. See [local development](docs/22-local-development.md)
for source edits, native debugging, data isolation, cleanup and CI. For the complete
commercial product, run the helper in the Cloud sibling repository instead; its
single HTTP app includes the core API and frontend. The public core runs independently.

Offline checks and optional local commit hooks:

~~~text
uv run --locked pre-commit install
uv run --locked --group dev --group evaluation python -m pytest -q
uv run --locked python -m ruff check .
uv run --locked python -m mypy
~~~

Prepare/validate the 120-file evaluation corpus and run opt-in live model checks (requires `OPENROUTER_API_KEY` in `.env`):

~~~text
uv run --group evaluation python -m scripts.prepare_corpus
uv run --group evaluation python -m scripts.validate_corpus
uv run --group evaluation python -m scripts.smoke_models
uv run --locked python -m ai_idp.evaluation.runner --live --allow-draft --max-total-cost-usd 0.50 --case-id synthetic-native-01 --case-id synthetic-scan-01 --case-id synthetic-mixed-01 --case-id synthetic-docx-01 --case-id cord-v2-train-0000 --limit 5 --profile default --profile always_vision
~~~

Python 3.13 is selected through `.python-version`. Original external files remain in ignored `eval/downloads/`. The corpus contains 70 PDFs, 20 DOCX files and 30 receipt PNGs; counterpart images do not count again. See the [120-file catalog](eval/CORPUS.md) and [evaluation setup](eval/README.md).

Apply `alembic upgrade head` to existing databases before starting the updated API/worker. Docker Compose runs migrations before API/worker startup. Collection extraction saves bounded output pages and assembles records in application code; it never asks a model to rewrite the entire combined list. Scalar conflicts still use bounded model reconciliation. Verification checks bounded values against original source batches and independently checks collection source counts. Limits and unavailable content remain explicit. See [Excel and paged results](docs/19-spreadsheets-and-paged-results.md).

DOCX blocks retain every embedded image. Unsupported embedded formats such as EMF are exposed as conversion warnings and are not sent as PNG inputs; absence remains unresolved when such images are unavailable. Since an embedded image is not a rendered Word page, the `always_vision` profile preserves semantic text alongside supported images for DOCX. Office-faithful page rendering remains deferred.

All execution paths, including `run_inline=true` and evaluations, take renewable exclusive job leases. Finished model calls are checkpointed with their usage and reused on retry. A crash between a provider response and durable checkpoint storage can still require repeating that call; spending limits are estimates checked before each new call and after reported usage, not hard provider billing caps.

Relevance scoring sends up to eight source units with images and text per request
(`RELEVANCE_BATCH_UNITS=8`, `MAX_DECISION_IMAGES_PER_CALL=8`), together with the
**complete extraction field set**. The classifier returns one relevance score per
unit for any requested field, not one score per unit/field pair. A 100-page PDF with
80 fields therefore needs 13 relevance requests when byte limits allow eight pages
per group. Up to eight groups run concurrently (`MAX_PARALLEL_DECISION_BATCHES=8`).
`RELEVANCE_STRATEGY=decisions` uses the configured decision classifier;
`RELEVANCE_STRATEGY=generative` returns one boolean/null flag per unit instead.
Threshold selection and a document-wide top-two safety floor retain source candidates.
All fields share this selected set; evidence, verification and recovery remain per field.
Image/byte/question limits, shared provider capacity and job-wide physical request budgets
still apply. See the [decision pipeline](docs/04-decision-pipeline.md). Pending v3 jobs
must be resubmitted after upgrading to v4; completed results remain accessible.

PostgreSQL concurrency and recovery regressions are opt-in: set `AI_IDP_TEST_POSTGRES_URL` to a development database and run `uv run --group dev --group evaluation python -m pytest -q tests/integration/test_postgres_leases.py`. Tests migrate and remove their own isolated schemas and make no model calls. CI configures offline tests on Windows, Linux and macOS and a separate PostgreSQL job.

For a complete client example, start API and worker and run:

~~~text
uv run --locked python examples/extract.py eval/fixtures/synthetic/synthetic-native-01.pdf --schema examples/record.schema.json
~~~

This submits paid model work. The script uploads, submits, polls and prints the result.
Inspect the API at `http://127.0.0.1:8000/docs`. Field verification and `schema_valid`
are separate: schema-valid data may remain unverified. Nested JSON Pointers, candidate
history, source text/images and paginated decisions are available for inspection.

## Core ideas

The engine also supports bounded [schema suggestions from example documents](docs/21-schema-suggestions.md).
Upload 1–5 related examples, generate a small editable schema, then reuse it in ordinary
extraction jobs. Suggestions run as separate durable, budgeted jobs on the same worker.

1. **Model-controlled relevance:** select document units relevant to the requested fields instead of automatically extracting from the entire file.
2. **Model-controlled modality:** decide between existing text, page images, or both, without content-dependent hard-coded routing heuristics.
3. **Evidence-bound results:** every extracted field can point to its original sources; a value is not considered verified merely because a generative LLM returned it.
4. **Field-level recovery:** verify each field, search for missing fields, and escalate uncertain or contradicted answers with bounded retries.
5. **Replaceable components:** hexagonal architecture makes model providers, document readers, storage, and queue implementations replaceable.
6. **Measurable value:** compare accuracy, evidence quality, latency, and full-pipeline cost against an always-vision baseline.

## MVP stack

- Python 3.13, uv, FastAPI, Pydantic v2 and Pydantic AI (`StructuredDict` + `OpenAIChatModel`).
- OpenRouter for decision and generative model calls. Baseline configuration: `perplexity/pplx-decider-v1.2` for decisions, `anthropic/claude-haiku-5.5` for primary extraction, and `google/gemini-4-argon` for escalation; all model IDs remain independently configurable.
- PyMuPDF for PDF text, metadata, and page rendering; Mammoth for lightweight DOCX-to-semantic-HTML extraction; Pillow for PNG, JPEG, and multi-frame TIFF inputs.
- PostgreSQL for jobs, checkpoints, evaluations, and a `SKIP LOCKED` leasing queue; local filesystem for original files and derived artifacts.
- OpenTelemetry SDK for spans and events, exported to rotating per-process JSONL (`telemetry/spans-*.jsonl`).
- pytest and reproducible, labeled real-model evaluation runs. The **120-file candidate corpus** is acquired: DocLayNet (35), CORD v2 (30), UK government PDFs (20), UK government DOCX (15), and synthetic stress files (20). Label review is pending; see [corpus status](eval/CORPUS.md) and [preparation policy](docs/12-evaluation-corpus.md).

## Scope

| Included in MVP | Explicitly deferred |
|---|---|
| HTTP file upload and async extraction jobs | S3 and presigned uploads |
| PDF, DOCX, PNG, JPEG, TIFF, XLSX, XLSM, XLS, XLSB; bounded OOXML formula arithmetic | Office-faithful page rendering and complete Excel formula compatibility |
| Schema-aware page-batch relevance and modality routing | Classical OCR, Docling, LibreOffice |
| Dynamic JSON Schema extraction | Fixed industry schemas |
| Provenance and field verification | Unrestricted autonomous agents |
| Coverage review and bounded escalation | SaaS billing, multi-tenancy, user authentication |
| PostgreSQL worker queue and telemetry | Redis, Celery, external telemetry backend |
| Repeatable evaluation with model comparisons | Uncalibrated confidence guarantees |

Deterministic **mechanical** operations are still required: parsing files, rendering PDFs, validating inputs and outputs, controlling resources, and enforcing security. They do not determine document relevance or text/vision strategy.

## Documentation

| Document | Contents |
|---|---|
| [Product requirements](docs/01-product-requirements.md) | Goals, journeys, MVP boundaries and acceptance criteria |
| [Architecture](docs/02-architecture.md) | Ports, adapters, orchestration, deployment |
| [Ingestion](docs/03-document-ingestion.md) | PDF, DOCX, raster inputs and source references |
| [Decision pipeline](docs/04-decision-pipeline.md) | Relevance, modality selection, uncertainty |
| [Extraction and verification](docs/05-extraction-verification.md) | Schemas, provenance, field checking, recovery |
| [API contracts](docs/06-api-contracts.md) | Request/response sketches and error conventions |
| [Data model](docs/07-data-model.md) | PostgreSQL entities and durable queue |
| [Observability](docs/08-observability-and-queue.md) | Worker operations, telemetry, limits |
| [Evaluation](docs/09-evaluation-strategy.md) | Ground truth, baselines, metrics, experiments |
| [120-document evaluation corpus](docs/12-evaluation-corpus.md) | Exact quotas, sources, licensing, annotation and data splits |
| [Implementation plan](docs/10-implementation-plan.md) | Ordered milestones and definition of done |
| [Decisions](docs/11-decisions-and-open-questions.md) | Architectural decisions and unresolved questions |
| [Operations and release gates](docs/13-operations-and-release.md) | Deployment, limits, schemas, backup/restore, human review and acceptance |
| [Local development and stack ownership](docs/22-local-development.md) | One-command core startup, full-product boundary, cleanup, native debugging and CI |
| [Page-batch validation](docs/16-page-batch-validation.md) | v4 routing contract, offline checks and the 72-file development run |
| [Excel and bounded-result research plan](docs/18-spreadsheets-and-bounded-results-plan.md) | Parser experiments, Excel scope, generation limits, resumable parts and result pagination |
| [Excel and paged results](docs/19-spreadsheets-and-paged-results.md) | Formats, parser safety, partition extraction, paging contract and UI |
| [Bounded formulas and large documents](docs/20-bounded-formulas-and-large-documents.md) | Formula calculation, nested results, on-demand PDF pages, work estimates and regressions |


## Public-project rules

- Never commit credentials, access tokens, passwords, .env files, private documents, or data derived from confidential sources.
- Test fixtures in the repository must be synthetic, public-domain, or appropriately licensed for redistribution.
- Do not log original document content or full model prompts by default.
- Model calls send document content to a third-party provider. This must remain explicit in deployment documentation.
- All repository materials, source code, comments, user-facing messages, and commit messages are in English.

See [Contributing](CONTRIBUTING.md) and [Security](SECURITY.md).
