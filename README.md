# AI-IDP

AI-IDP is an open-source, general-purpose Intelligent Document Processing (IDP) project. It explores **AI-directed document understanding**: a decision model selects the document content and processing modality needed for a caller-defined extraction schema, generative models extract structured values, and an independent decision model checks field-level evidence.

The project begins as a self-hosted HTTP API and may later evolve into a production service or SaaS product. It is **not specific to any industry, employer, or proprietary document workflow**.

**Status:** Architecture and implementation specification (MVP). No application code is included yet.

**License:** [Apache License 2.0](LICENSE). Contributions and dependencies must be compatible with permissive open-source distribution.

## Core ideas

1. **Model-controlled relevance:** select document units relevant to the requested fields instead of automatically extracting from the entire file.
2. **Model-controlled modality:** decide between existing text, page images, or both, without content-dependent hard-coded routing heuristics.
3. **Evidence-bound results:** every extracted field can point to its original sources; a value is not considered verified merely because a generative LLM returned it.
4. **Field-level recovery:** verify each field, search for missing fields, and escalate uncertain or contradicted answers with bounded retries.
5. **Replaceable components:** hexagonal architecture makes model providers, document readers, storage, and queue implementations replaceable.
6. **Measurable value:** compare accuracy, evidence quality, latency, and full-pipeline cost against an always-vision baseline.

## MVP stack

- Python 3.13, uv, FastAPI, latest compatible stable Pydantic v2 and Pydantic AI (resolved and locked during implementation).
- OpenRouter for decision and generative model calls. Initial decision candidate: Perplexity Decider V1.2; extraction and escalation models are independently configurable.
- PyMuPDF for PDF text, metadata, and page rendering; Mammoth for lightweight DOCX-to-semantic-HTML extraction; native support for image inputs.
- PostgreSQL for jobs, checkpoints, evaluations, and a leasing queue; local filesystem for original files and derived artifacts.
- OpenTelemetry for spans and metrics, exported to local JSONL initially.
- pytest and reproducible, labeled real-model evaluation runs.

## Scope

| Included in MVP | Explicitly deferred |
|---|---|
| HTTP file upload and async extraction jobs | S3 and presigned uploads |
| PDF, DOCX, PNG, JPEG, TIFF | Office-faithful page rendering |
| Field-aware unit relevance and modality routing | Classical OCR, Docling, LibreOffice |
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
| [Implementation plan](docs/10-implementation-plan.md) | Ordered milestones and definition of done |
| [Decisions](docs/11-decisions-and-open-questions.md) | Architectural decisions and unresolved questions |

## Public-project rules

- Never commit credentials, access tokens, passwords, .env files, private documents, or data derived from confidential sources.
- Test fixtures in the repository must be synthetic, public-domain, or appropriately licensed for redistribution.
- Do not log original document content or full model prompts by default.
- Model calls send document content to a third-party provider. This must remain explicit in deployment documentation.
- All repository materials, source code, comments, user-facing messages, and commit messages are in English.

See [Contributing](CONTRIBUTING.md) and [Security](SECURITY.md).
