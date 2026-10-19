# Bounded formulas and large-document processing

Implemented 2026-10-19. Extends the [paged result contract](19-spreadsheets-and-paged-results.md).

## Formula calculation

XLSX/XLSM shared formulas retain their master/follower attributes and expand relative
references. The deterministic interpreter supports decimal arithmetic, compatible
scalar comparisons, percentages, bounded cross-sheet A1 references, and `SUM`,
`AVERAGE`, `MIN`, `MAX`, `COUNT`, `ABS`, `ROUND`, and three-argument `IF`.
This is a subset, not Excel's full engine. `IF` evaluates both branches; unsupported
or erroneous branches leave calculation unsupported. Implicit scalar text conversions,
array/data-table formulas, named ranges, external workbooks, VBA/XLM, add-ins, network
and filesystem functions are unavailable. XLS/XLSB retain cached-value capabilities.

Limits: 4,096 formula characters, 512 tokens, depth 32, and 128 direct/transitive
inputs per formula. Workbook limits are configurable: `MAX_FORMULA_CELLS=100000`
and `MAX_FORMULA_STEPS=100000`. Exceeding the index limit disables recalculation
explicitly. Cycles, excessive ranges/exponents and source errors stay explicit.
Calculation stays in the killable decoder; no Python `eval` is used. Original caches
are retained independently and can be fallback values, without a freshness guarantee.

Previews return bounded cell records, formula attributes, original caches, calculation
status/reason and input sheet/cell/value references. Derived values use `calculated`
and engine `bounded-arithmetic-v1`. Cell-anchored citations retain derivation metadata.
The Cloud grid distinguishes calculated, saved-only and unavailable results and
exposes formulas and inputs. Calculation does not replace field-meaning verification.

## Nested results and continuation

Verification recursively partitions large object wrappers and nested arrays, retaining
bounded values and real citations. Oversized indivisible scalars still fail explicitly.
A portion-checked object wrapper is only promoted after every descendant passes
verification and collection coverage. Semantic insufficiency is not overridden.

Continuation consumes a record anchor rather than a whole worksheet row or PDF line.
Models can return a unique record-end quote; otherwise the remaining tail stays
available. Multiple records on one row remain distinct. Internal partition names use
provider-compatible aliases while result/evidence JSON Pointers remain canonical.
Adjacent text context includes original source unit IDs, so a record can cite values
continuing on the next page while retaining ownership at its original start.

## PDF preparation

Default local storage prepares text, geometry and deferred image descriptors. Images
are rendered only for preview or model requests, in monitored child processes using
immutable originals. A per-document cache holds at most 64 MiB of generated images,
or the smaller expanded-artifact limit. SQLite locks coordinate cache reads, writes
and eviction across API/worker processes. Only generated images can be evicted.
Injected blob stores without deferred-artifact support retain eager rendering.

Payloads retain image references and load image bytes per bounded request. Text-only
processing does not render or load PDF images. Prepared text/eager non-PDF artifacts
still use `MAX_PREPARED_INPUT_MIB`; model byte/image limits bound PDF requests.
Admission limits of 200 MiB/1,000 pages remain separate from defaults of 128 extraction
parts, 250 physical calls and 600 job seconds. This does not change model-controlled
routing, promise unlimited extraction or establish large scanned-PDF accuracy.

## Work estimate and UI

`POST /v1/documents/{document_id}/estimate` accepts extraction schema, instructions
and profile without provider calls. It reports minimum routing requests, an all-units,
one-output-page planning scenario, budget ceilings, assumptions and warnings. Value
checks, extra pages, byte splits and recovery are additional. It is not a price quote.
Submission rejects jobs whose minimum routing alone exceeds their call budget; an
uncertain all-units forecast produces warnings. Normal tenant/CSRF protections apply.

Cloud shows estimates during preview/submission and after refresh. Collection
completeness appears above each table separately from leaf-value badges, with the
unresolved reason. Page changes retain global indices, clear stale source details
and redraw highlights. Excel uses a sparse coordinate grid with formula/input details
and cell highlighting. Full JSON download remains separate from displayed-slice CSV
and clipboard actions. Nested arrays within a displayed record remain part of it.

## Regressions and opt-in live check

Offline regressions cover 300 nested records with exact export, two records on one
worksheet row, shared/stale/missing formula caches, dependency chains, unsupported
and resource-heavy formulas, and a 40-page PDF prepared without rendered images.
Text-only batching renders nothing; loading one requested page creates one image.
Existing paging/replay, source-hash and rotated-PDF geometry checks remain active.

Set `AI_IDP_RUN_LIVE_REVIEW=1` using the current shell's environment syntax, then run:

```text
uv run --locked --group dev --group evaluation python -m pytest -q -s tests/integration/test_live_bounded_documents.py
```

The opt-in check uses only a generated 12-record workbook, two sheets, nested schema
and three-record responses, with a USD 0.10 estimated cap, 64 calls and no retries or
field recovery. Otherwise it is skipped. Actual provider charges may differ from
recorded estimates. Corpus identities, splits and AI-reviewed references are unchanged;
synthetic smoke checks are not human-approved benchmark evidence. Outputs and runtime
QA databases stay ignored. Mypy uses its supported Python parser because this Windows
host blocks the native AST extension; configured domain/port type checks remain active.
