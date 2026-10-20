# 11 — Architecture Decisions and Open Questions

## Accepted decisions

**ADR-001 — Public, permissive, industry-neutral.** The repository is an open-source project licensed Apache 2.0. The core pipeline must not assume any particular document industry or employer. SaaS is a possible future deployment model, not a current architectural constraint.

**ADR-002 — AI-driven content decisions.** Use a decision model for field-aware unit relevance and modality routing. Deterministic operations for safe decoding, metadata extraction, validation and infrastructure are allowed. Do not add deterministic content routing heuristics during the first experiment.

**ADR-003 — Lightweight DOCX.** Use Mammoth to extract semantic HTML and logical blocks without rendering Word page layouts. DOCX provenance uses semantic block IDs, not fictional physical page numbers. No headless LibreOffice in the MVP.

**ADR-004 — One model gateway.** Use OpenRouter for decision and generative model APIs in the MVP. Keep model identity and capabilities configurable, with an initial smoke-tested baseline of `perplexity/pplx-decider-v1.2` (decision/verification), `anthropic/claude-haiku-5.5` (primary extraction), and `google/gemini-4-argon` (escalation). Use Pydantic AI for generative extraction, and a dedicated typed httpx adapter for the Decisions API (`POST /api/alpha/decisions`).

**ADR-005 — PostgreSQL-only queue.** Use an existing PostgreSQL server for persistence, durable job state, and leased worker polling. No Redis or Celery for MVP.

**ADR-006 — Local-first storage and telemetry.** Local original/derived files behind ports; OpenTelemetry SDK exporting JSONL locally. Future S3 and external observability systems should be adapter changes. S3-compatible storage is now an optional adapter (`STORAGE_BACKEND=s3`) that keeps a local read-through cache.

**ADR-007 — Field-level evidence and verification.** Each field may have multiple evidence references. Use independent supported/contradicted/insufficient-evidence decisions, preserve raw probabilities and bounded escalation. Never claim raw model probability equals calibrated truth likelihood.

**ADR-008 — Evaluation-first.** Build a public safe dataset and a full-vision baseline. Measure missed evidence, false verification acceptances, field correctness, cost and latency; do not claim improvements without data.

**ADR-009 — English-only repository.** All documentation, code, tests, comments, errors, examples, commit messages, and contributions in the repository must be in English.

**ADR-010 — Fixed initial 120-document evaluation corpus.** Before substantial application implementation, prepare a documented, licence-reviewed, human-annotated corpus comprising 35 DocLayNet PDF pages, 30 CORD v2 receipts, 20 UK government PDFs, 15 UK government DOCX files, and 20 synthetic stress documents. Freeze 72 development, 24 calibration and 24 holdout cases using grouped, nonleaking splits. Track source licences separately from Apache-2.0 code licensing. See [the corpus specification](12-evaluation-corpus.md).

**ADR-011 — Portable Python development.** Development currently takes place on Windows;
the supported target platforms are Windows, Linux and macOS. Use Python 3.13, uv-managed
environments, `uv run` entry points, `pathlib`, and a committed cross-platform dependency
lock. Avoid shell-specific activation and OS-specific runtime assumptions. Initial bootstrap
verification is on Windows; Linux/macOS verification remains pending.

**ADR-012 — Complete-schema page-batch relevance (2026-10-18).** Replace v3
unit/field questions with one question per source unit relative to any requested
field. Every request receives the full field set and up to eight units/images,
subject to byte and provider limits; up to eight groups run concurrently. Live
provider checks accepted eight images and rejected nine. Use a threshold plus a
document-wide top-K safety floor, retain raw unit scores and original source order,
and keep downstream field evidence, verification and bounded recovery. Optional
fields remain search targets. Pending v3 jobs require resubmission rather than
reinterpretation of their saved checkpoints.

## Open questions for implementation experiments

1. Which JSON Schema constructs are reliably supported by the chosen generative models (`anthropic/claude-haiku-5.5`, `google/gemini-4-argon`) and Pydantic AI pipeline (especially nested arrays, union types and $ref)?
2. How does question batching vs single-question invocation affect accuracy and latency on the OpenRouter Decisions API (`POST /api/alpha/decisions`, verified for `image_url` + text state, `noul`/`choice`/`score` criteria, and token billing via `scripts.smoke_models`)?
3. How should probabilities from different decision tasks and models be normalized without misrepresenting confidence?
4. Which relevance threshold/top-K recovery policy yields acceptable page recall? Evaluate on labeled data.
5. When is DOCX semantic conversion insufficient to capture visual-only content? Measure, then decide whether an optional renderer is justified.
6. How does the baseline `anthropic/claude-haiku-5.5` + `google/gemini-4-argon` pair compare against alternatives (such as `google/gemini-3.8-flash` or `qwen/qwen3.8-flash`) on verified-field cost and accuracy?
7. Should image rendering happen eagerly or lazily for very long PDFs?
8. Which JSONL exporter implementation works best with the latest OpenTelemetry SDK, while supporting rotation and privacy defaults?
9. Which exact per-file reuse licences and attributions apply to selected government documents and third-party PDFs, and which upstream binaries may be redistributed? Resolve each in the corpus manifest before publication.
10. Before offering SaaS, how should authentication, tenant isolation, deletion/retention, encryption, billing and third-party processing agreements be implemented?

## Non-decisions

Specific model pricing, raw probability thresholds, business field semantics, commercial hosting provider, and final production SLAs are intentionally not locked at the specification stage.
