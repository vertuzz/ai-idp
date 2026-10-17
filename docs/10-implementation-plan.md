# 10 — Implementation Plan

This plan orders work so that model behavior is exercised against real documents before the pipeline grows complex. Each milestone includes runnable tests and documentation.

## M0 — Curate the evaluation corpus (before substantial application implementation)

- Adopt [the 120-document corpus plan](12-evaluation-corpus.md) and [machine-readable source quotas](../eval/corpus-plan.yaml).
- Select a 20–30-document, diverse, licence-reviewed preview subset for the earliest real-model tests.
- Freeze the eventual 120 source identities and their group-safe split: 72 development, 24 calibration, 24 holdout.
- Record publisher/dataset, original link and revision, checksum, file-specific reuse rights and attribution per case.
- Annotate extraction schemas, expected field values and original page/block evidence; human-review ambiguous cases.
- Keep large/third-party document binaries local unless redistribution has been expressly cleared.
- Prepare evaluation harness contracts and corpus validation; do not invent sample IDs or claim labels exist before annotation.

**Done when:** an approved preview corpus exists with reproducible source inventory and reviewed field/evidence labels; the full 120-document corpus plan is pinned for subsequent expansion.

## M1 — Foundation

- Project/package layout using Python 3.13 and uv.
- Resolve latest mutually compatible stable FastAPI, Pydantic v2, Pydantic AI, httpx and supporting packages; commit uv.lock.
- Structured settings and .env.example, no secrets.
- FastAPI application with /health/live and /health/ready.
- PostgreSQL connection, SQLAlchemy schema and Alembic initial migration.
- File storage port and local adapter.
- pytest, lint/type-check setup and Docker Compose for API, worker and PostgreSQL.

**Done when:** a clean checkout starts locally; tests pass; PostgreSQL migrations run; a file can be uploaded and stored without invoking models.

## M2 — Document normalization

- PyMuPDF PDF page metadata, native text extraction and cached page previews.
- Mammoth DOCX semantic HTML and block extraction, table structure and embedded image handling; no LibreOffice.
- PNG/JPEG/TIFF frame support and source locators.
- Size, decompression, frame/page count and runtime limits.
- Unit tests for reading order, table and image cases, DOCX block references.

**Done when:** heterogeneous files normalize to stable DocumentUnit structures with usable source artifacts.

## M3 — Decision integration

- Typed OpenRouter Decisions API adapter using httpx.
- Capability smoke tests for image state, question types and response shapes.
- Field-aware relevance and modality selection with configurable candidate policies.
- Persist model results, raw probabilities, policy versions and usage.
- Real-model tests on a handful of representative documents; compare batched vs unbatched questions.

**Done when:** relevant units and TEXT/VISION/TEXT_AND_VISION routes are inspectable and reproducible.

## M4 — Structured extraction

- OpenRouter generative model integration via Pydantic AI.
- Dynamic JSON Schema translation/validation and explicit unsupported-schema policy.
- Extraction grouping, source provenance, nullable/missing fields, partial schema semantics.
- Field result API with evidence references.
- Baseline that bypasses relevance routing and processes all units with vision.

**Done when:** an API consumer can retrieve typed values and trace their sources for PDF, DOCX and image examples.

## M5 — Verification, escalation and coverage

- Field-level three-way decision verification.
- Separate raw scores from calibrated correctness claims.
- Bounded retry/escalation, candidate version history and stronger model profile.
- Missing-field coverage review against previously unselected units.
- Recover to unresolved rather than fabricate values.

**Done when:** tests demonstrate contradiction detection, missing-field discovery and controlled failure outcomes.

## M6 — Operations and evaluation

- PostgreSQL leasing worker with SKIP LOCKED, checkpoints and crash recovery.
- Global and per-model concurrency/rate limits, spend/time ceilings.
- OpenTelemetry local JSONL with safe default attributes.
- Evaluation runner, the complete and reviewed 120-document corpus with frozen 72/24/24 splits, always-vision baseline and metrics.
- Public README usage example, security/contribution docs and compatibility validation.

**Done when:** the system survives worker interruption and emits a repeatable measured comparison on real OpenRouter models.

## Milestone conventions

- Implement thin vertical slices; avoid large untested interface hierarchies.
- Run real integration tests with small budgets before designing around assumptions of provider behavior.
- Do not introduce Redis, Celery, Docling, classical OCR, LibreOffice, or business-specific rules without a documented change in scope.
- Record architectural changes in the decisions document.
- Pin dependencies by lockfile but periodically reassess for security and upstream API changes.
