# 01 — Product Requirements

## Objective

Provide a general-purpose document-to-structured-data API for arbitrary caller-supplied JSON Schemas. The core experiment is whether decision-model-led relevance and text/vision routing can retain extraction quality at lower end-to-end cost than always sending all document units to a vision-capable LLM.

This is a public, permissively licensed product experiment, not a company-specific integration. Future hosted and SaaS offerings are possibilities, not MVP requirements.

## Primary journeys

1. **Upload:** a client uploads a supported file and receives an immutable document ID.
2. **Extract:** a client submits a JSON Schema, optional natural-language instructions, and a document ID; receives a durable job ID.
3. **Track:** a client polls the job and sees processing stage, progress, failure information, and cost.
4. **Inspect:** a client retrieves structured data, per-field provenance and verification state, missing fields, and attempts.
5. **Experiment:** a developer reruns the same document/schema with different model configurations and compares it to labeled reference results.

## Functional requirements

- Accept PDF, DOCX, PNG, JPEG and multi-frame TIFF; reject unsupported/unsafe inputs with explicit errors.
- Store original bytes and derive stable unit IDs. Reuse prepared documents across extraction runs.
- PDF units are physical pages with native text, image, and basic geometry/metadata.
- DOCX units are semantic blocks with HTML/text, tables and associated embedded images; physical page numbers are not promised.
- Image units are single images or frames; source references must remain stable.
- Support object-shaped caller JSON Schemas with nested fields and arrays as a goal; validate and state any unsupported features explicitly.
- Relevance decisions consider **the requested fields** and the unit's available text, metadata, and image where applicable.
- Keep decision probabilities and a candidate shortlist rather than discarding uncertain units irreversibly.
- Route selected units to TEXT, VISION or TEXT_AND_VISION; both paths may be used when warranted.
- Extract nullable values plus evidence (source unit ID, excerpt and optional geometry). Never invent values to satisfy a required schema.
- Verify fields against original evidence and permit SUPPORTED, CONTRADICTED, or INSUFFICIENT_EVIDENCE.
- Reconsider unfilled or unverified fields with a coverage review before finalizing.
- Perform bounded extraction escalation on uncertain/contradicted fields and preserve attempt history.
- Serve durable asynchronous jobs from a PostgreSQL-backed worker, with retries and recovery.
- Provide OpenTelemetry instrumentation and labeled-model evaluation.

## Nonfunctional requirements

- **Portability:** local container deployment first; PostgreSQL is the only external infrastructure requirement.
- **Safety:** file-size, expanded-content, page-count, time, concurrency, and spending limits are configurable.
- **Reproducibility:** record model IDs, effective parameters, prompt/policy versions and pipeline version.
- **Transparency:** return error/unknown states rather than asserting that unverified results are correct.
- **Cost-awareness:** apply bounded candidate selection, token limits, and per-job budget accounting.
- **Open source:** Apache-2.0-compatible code and dependencies; no credentials or proprietary fixtures in git.
- **Privacy:** avoid storing sensitive prompt payloads and source text inside traces by default; protect local job artifacts.

## MVP acceptance criteria

- One end-to-end HTTP request sequence works for a multipage PDF, a DOCX with tables, and an image input.
- A single document can be processed with two different schemas without re-uploading.
- Relevance and modality decisions and probabilities are inspectable for each processed unit.
- Every output leaf has a verification status and an evidence reference or an explicit missing/unresolved reason.
- Worker restart does not lose a job; duplicate execution does not create duplicate finalized outputs.
- Actual OpenRouter calls are covered by a small integration suite, with mocked tests covering errors/timeouts.
- Evaluation can compare at least two configurations with an always-vision baseline.
- No secrets, non-redistributable customer documents, or organization-specific assumptions exist in the public repository.

## Explicit non-goals

Classical OCR engines, Docling, LibreOffice, a general scripting-agent parser, custom model hosting, user management, billing, distributed message brokers, and guaranteed perfectly calibrated probabilities are excluded from the first version.
