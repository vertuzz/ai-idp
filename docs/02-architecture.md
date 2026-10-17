# 02 — Hexagonal Architecture

## Design

Keep the domain independent from FastAPI, OpenRouter, PyMuPDF, Mammoth, filesystem paths, and database libraries. One deployable application exposes the HTTP API and one or more worker processes; neither is a separate domain microservice.

~~~text
HTTP client
    |
FastAPI adapter ----> IngestDocument / RequestExtraction / GetJob / GetResult
                            |
                    Application orchestrator
                            |
                Domain models + outbound ports
                   /       |       |       \
      DocumentReader  DecisionEngine  ExtractionEngine  JobRepository
          |                |               |                 |
    PDF/DOCX/Image    OpenRouter API   Pydantic AI       PostgreSQL
          |
       BlobStore ------------------------------------------> local files
~~~

## Domain objects

- **Document:** immutable source identity, type, checksum, store reference.
- **DocumentUnit:** stable unit ID; page/frame/semantic-block kind; ordered position; extracted native text; optional image; metadata and pointers to original content.
- **ExtractionSpecification:** normalized user schema, field descriptions, instructions, schema fingerprint.
- **CandidateUnit:** source unit + targeted fields + relevance output/probabilities.
- **ModalityDecision:** TEXT, VISION or TEXT_AND_VISION, evidence/rationale metadata, probabilities and policy version.
- **FieldValue:** JSON path, value or null, source references, verification status, diagnostic score(s), attempts.
- **Evidence:** source unit ID, quoted span or location, optional bounding box; support multiple sources per field.
- **ExtractionRun:** document, schema, model/policy configuration snapshot, usage, progress, status, result.
- **DecisionRecord:** immutable request/response metadata and score distributions.
- **EvaluationCase/Run:** expected output, annotations, configuration and measured outcomes.

## Outbound ports (Python Protocol or ABC)

- DocumentBlobStore: put, get, delete, checksum, derived artifacts; local first, S3 later.
- DocumentReader: inspect and normalize a file into DocumentUnit objects with capabilities.
- DecisionEngine: score relevance and extraction strategy; verify candidate fields; optional coverage review.
- ExtractionEngine: produce schema-constrained, evidence-linked candidates from selected units.
- JobRepository: create, lease, heartbeat, checkpoint, finalize, retry, inspect.
- ResultRepository: persist attempts, decisions, field evidence, final outputs.
- TelemetryPort: record domain events and measurements without exposing backend-specific APIs.
- Clock / ID generator abstractions only where needed for tests.

The VerificationEngine may start as an application service orchestrating a DecisionEngine rather than adding an unnecessary model-provider layer.

## Inbound adapters

- FastAPI HTTP router and request validation.
- PostgreSQL worker runner and operational CLI.
- Evaluation CLI (dataset preparation, replay, scoring).

## Outbound adapters

- PyMuPDF PDF reader/renderer; Mammoth DOCX semantic reader; Pillow or equivalent raster reader.
- OpenRouter Decisions API via typed httpx adapter. Decision calls are not standard chat completions.
- OpenRouter generative models via Pydantic AI. Keep native JSON Schema support and fallback strategy behind an adapter.
- SQLAlchemy + psycopg + Alembic; filesystem blob adapter; OpenTelemetry SDK exporters.

## Application workflow

1. Ingest and prepare source units, storing durable references.
2. Normalize field targets from ExtractionSpecification.
3. Score all units for field-aware relevance, accounting for continuations and context.
4. Build a field-to-candidate-unit map with uncertainty preservation.
5. Score modality per selected unit/field-group; prepare native text and/or page image.
6. Group related field requests and source units into bounded extraction calls.
7. Validate structured output shape and attach source evidence.
8. Verify each populated field against original units (not solely generative model summaries).
9. Retry/escalate unresolved fields; review missing-field coverage.
10. Finalize structured result with per-field status and complete diagnostics.

## Separation and extensibility

- Upload transport must not determine storage; future presigned S3 is an HTTP adapter + blob store change.
- DOCX's semantic units must not pretend to be physical pages.
- Caller schemas and industry semantics are supplied as data, not embedded in the core.
- Model IDs, capabilities, prices and risk thresholds are configuration, not domain invariants.
- Provider-specific response format details belong in adapters; domain stores normalized decisions.
- All steps should be independently replayable for evaluation.

## Repository layout (target)

~~~text
src/ai_idp/
  domain/
  application/
    use_cases/
    services/
    ports/
  adapters/
    inbound/http/
    outbound/documents/
    outbound/openrouter/
    outbound/persistence/
    outbound/storage/
    outbound/telemetry/
  workers/
  evaluation/
  settings.py
tests/
  unit/
  integration/
  evaluation/
docs/
migrations/
~~~

Avoid large generic repository classes and infrastructure logic in domain services.
