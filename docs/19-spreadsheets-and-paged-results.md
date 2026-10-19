# Excel ingestion and paged extraction results

Implemented on 2026-10-18. This documents the delivered behavior; the earlier
[research plan](18-spreadsheets-and-bounded-results-plan.md) also contains proposals
that are not all implemented defaults.

The [2026-10-19 extension](20-bounded-formulas-and-large-documents.md) adds bounded
formula calculation, shared-formula recovery, nested verification, coordinate grids,
explicit table coverage, on-demand PDF pages and work estimates.

## Reading workbooks

Uploads accept XLSX, XLSM, XLS and XLSB alongside PDF, DOCX and images. OOXML workbooks
are decoded as sparse XML cells, with protected XML parsing and ZIP expansion/entry
limits; XLS/XLSB use python-calamine. Decoding stays in the existing killable process
with memory, elapsed-time and generated-artifact budgets. Encrypted workbooks fail
with `encrypted_document`; decrypt them outside the service before uploading.

Macros, workbook connections and external resources are never executed or fetched.
OOXML formula arithmetic uses a bounded deterministic interpreter in the isolated
decoder. Formula text, cached values, number formats, date epoch, hidden
sheet state and cell coordinates remain available. A cached empty string is distinct
from a missing cache. Cached values are not a freshness guarantee. Binary workbook
formula text/styles/drawings and chart rendering have explicit capability warnings;
they cannot silently establish absence. Embedded OOXML images are retained as workbook
context without fabricated drawing anchors. Office-faithful rendering, full Excel
formula compatibility, ODS, CSV and Excel template extensions remain deferred.

Style-only blanks and unused rectangular dimensions are ignored. Zero, false and
zero-padded identifiers remain data. Each bounded source range retains literal cell
addresses, so skipping empty cells never shifts another value into its column.
Leading sheet context is labeled context-only; source ownership is separate. Models
still decide relevance, field meaning, record grouping and supported modality.
Sheet/range previews and uniquely anchored cell citations work in the Cloud playground.

## Admission and execution limits

All limits are configurable and independent. File admission does not promise that
extracting every record will fit a job's model budget.

| Setting | Default |
|---|---:|
| `MAX_UPLOAD_MIB` | 200 |
| `MAX_PDF_PAGES` | 1,000 |
| `MAX_SPREADSHEET_SHEETS` | 128 |
| `MAX_SPREADSHEET_CELLS` (actual content/formulas) | 2,000,000 |
| `MAX_DOCUMENT_UNITS` | 10,000 |
| `SPREADSHEET_ROWS_PER_UNIT` | 25 populated rows |
| `MAX_UNIT_TEXT_CHARACTERS` (workbook cells/tiles) | 16,000 |
| `MAX_DOCUMENT_TEXT_CHARACTERS` (decoded text, conservatively bounded) | 32,000,000 |
| `MAX_EXPANDED_MIB` / `DOCUMENT_MEMORY_MIB` | 1,024 / 1,024 |
| `DOCUMENT_TIMEOUT_SECONDS` / `MAX_JOB_SECONDS` | 600 / 600 |
| `MAX_OUTPUT_TOKENS` | 8,192 per generation |
| `EXTRACTION_PAGE_ITEMS` | 25; automatically halved after length errors |
| `MAX_EXTRACTION_PARTS` | 128 per partitioned extraction invocation |
| `MAX_EXTRACTED_FIELDS` (containers and leaves) | 50,000 |
| `MAX_RESULT_BYTES` | 32 MiB |
| `RESULT_PAGE_BYTES` | 1 MiB |
| `MAX_MODEL_CALLS` / `MAX_JOB_ESTIMATED_COST_USD` | 250 / estimated USD 10 |

There is no calibrated 6,000-token planning guarantee in this release. Row-count
planning, hard generation limits and adaptive halving bound responses. A single
indivisible record/value that still exceeds a limit fails explicitly; it is never
shortened and presented as complete. Deeply nested collections inside a single
oversized record remain subject to that record limit. Schema complexity limits are
unchanged. Prepared text and eager non-PDF input remain bounded by `MAX_PREPARED_INPUT_MIB`;
this is not an unbounded million-row streaming analytics engine.

## Extraction, recovery and verification

Array fields are extracted per owned source unit in complete JSON output pages.
The model returns record anchors, continuation metadata, values and leaf evidence.
For native text, anchors must resolve in the owned suffix in increasing source order.
The application advances the original-text position, retaining canonical source
identity and remapping page-local pointers to global item indices. Equal source
records are preserved. Source ownership prevents overlap/replay from becoming
duplicate output. Vision-only continuation also remains subject to model/source
verification; a syntactically valid response is not proof of complete extraction.

Each finished model call is checkpointed with usage. Output-length errors, including
schema-valid JSON with a `length` finish, cannot become successful completed pages.
The application halves the record limit and retries smaller work, preserving split
decisions and earlier pages. Scalars use bounded field groups and split further on
output limits; object fields can be split into child targets. Collections are joined
by application code, with no full-array generative merge.

Independent source-count checks can trigger one bounded re-extraction of a source
whose candidate record count is contradicted. The source portion is replaced, not
blindly appended; saved earlier candidates remain explicitly provisional history.
Final collection coverage is checked across every prepared unit, including units
relevance did not select. A collection is not promoted on its extractor's stop flag.
Every record/leaf also needs source-based verification and mechanical evidence checks.
If the model supplies a record anchor but omits a leaf citation, a unique literal
value inside that original record span can supply mechanical provenance. Decimal
equivalents are allowed for numbers; cell addresses are excluded from numeric
matches. Ambiguous matches remain uncited, and explicit model citations are not
overwritten. This anchoring never replaces independent semantic verification.
Verification splits large values into portions. Count checks are model decisions,
not a mathematical proof or calibrated correctness probability; ambiguous counts,
unavailable content and contradictions remain unresolved.

Request/spend/time budgets include all new extraction/count/recovery/verification
calls and physical retries. Large source-by-field verification can exhaust those
budgets even when parsing succeeds. Saved provisional parts remain inspectable after
failure/cancellation. A provider response lost before durable checkpointing may need
to be paid for again; cost ceilings remain estimates, as in the existing pipeline.

## HTTP delivery

All routes use the normal API authentication and Cloud tenant ownership checks.

- `GET /v1/extractions/{job_id}/result/manifest`: finalized scalar/object skeleton,
  collection paths/counts, schema validity, field diagnostics summary and final revision.
- `GET .../result/collections?path=/items&cursor=...`: one stored collection page,
  global `start_index`, items, matching field diagnostics and `next_cursor`. Pages have
  at most 100 items and are reduced to the byte cap. Cursors bind job/path/final revision.
- `GET .../result/parts?after=...&limit=10`: durable provisional candidates during work
  or after failure; always distinguish them from independently verified final data.
- `GET .../result/export`: full data JSON, serialized incrementally from stored pages.

Queries fetch bounded database records instead of loading the complete result and
slicing it in the HTTP handler. A record too large for the delivery cap fails explicitly.
`GET .../result` stays compatible for small outputs. New results above 100 collection
items or 1,000 diagnostic fields return `413 result_requires_pagination` on that route.
Historical completed jobs without a stored paged view remain accessible through the
original endpoint. No database migration is needed: paged projections reuse the
existing leased, immutable `job_steps` checkpoints.

The Cloud frontend accepts all four Excel formats, shows sheets/ranges and cells,
shows provisional latest-row previews while processing, navigates finalized result
pages with global source pointers and downloads the complete JSON. Table CSV and
clipboard actions explicitly describe the displayed slice. Refresh resumes the
existing job rather than submitting another paid extraction. Nested arrays inside a
displayed record remain part of that record; this release does not introduce a
separate independent table navigator for each inner array.

## Evaluation and reproducibility

The original 120-case manifest/splits remain unchanged. New parser research candidates
are pinned in `eval/spreadsheet-research-sources.json`, with source URLs, SHA-256 and
provisional rights status. None is called reviewed extraction ground truth. External
originals, real model outputs, QA accounts/databases and large generated files stay
ignored. `scripts.generate_spreadsheet_fixture` generates a project-owned register
with predictable IDs/amounts, multiple sheets and a distant styled blank.

```text
uv sync --locked --group dev --group evaluation
uv run --locked --group evaluation python -m scripts.validate_corpus
uv run --locked python -m scripts.generate_spreadsheet_fixture --rows 105 --sheets 2
uv run --locked --group dev --group evaluation python -m pytest -q
uv run --locked --group dev python -m ruff check .
uv run --locked --group dev python -m mypy
```

Cloud verification additionally runs its Python suite and `node --test tests/web/*.test.mjs`.
Real-provider verification results and the owner-authorized USD 2 spending accounting
are recorded below after completion. These are synthetic smoke checks, not a general
Excel/PDF accuracy benchmark or independent human-reference acceptance.
