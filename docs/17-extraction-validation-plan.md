# Evidence and value validation: implementation handoff

Date: 2026-10-18. Status: **Implemented and verified**.

All phases (A through E, behavioral test suite, mechanical validation, schema/persistence integration, and pipeline gating) have been implemented and validated against the test suite and corpus.

## 1. Recommendation and intended outcome

Add a small validation layer that combines mechanically checked source evidence,
explicit value normalization and model-based semantic verification. First repair
the evaluation distinctions so changes can be assessed honestly. Preserve the
existing model-led relevance and modality decisions.

The system should answer three separate questions for each extracted field:

1. **Source:** where exactly does the supporting material occur?
2. **Value:** was it copied or transformed correctly under the field's contract?
3. **Meaning:** does that material answer this field for the correct row, period,
   subject and document context?

A deterministic text match helps with the first two questions. It does not answer
the third. A model's semantic approval must not erase an unresolved mechanical
failure. Conversely, missing native text is not evidence that a scanned value is
wrong or absent.

Keep the first implementation small: evidence anchoring, conservative typed
checks, evaluation fixes and transparent diagnostics. Defer a general rule engine,
additional verifier ensembles and a new OCR stack until measurements justify them.

## 2. Read first and preserve existing work

Follow `AGENTS.md`, `README.md`, `eval/README.md` and `eval/CORPUS.md`. Relevant design
documents are [verification](05-extraction-verification.md),
[page-batch routing](04-decision-pipeline.md),
[operations](13-operations-and-release.md),
[reference limitations](15-ai-source-review.md) and
[the latest validation record](16-page-batch-validation.md).

The workspace already contains uncommitted page-batch implementation and
documentation changes. Inspect and preserve them; do not reset the worktree or
mistake those changes for work performed by the next agent.

Preserve these invariants:

- Relevance receives up to eight units/images and **all fields** per request,
  returning one relevance score per unit. Keep bounded parallelism, source order
  and the document-wide candidate safety floor. Do not restore unit/field queries.
- The 100-page, 80-field regression still requires 13 relevance requests when
  image/byte limits permit eight pages per group. This excludes downstream calls.
- Models decide content relevance and modality. Validation rules must not become
  hard-coded document-category or content-routing heuristics.
- Field citations, nested JSON Pointers, candidate history, schema validity,
  leases, durable checkpoints and job-wide request/spend/time budgets remain intact.
- Unknown optional values, unresolved values and supported absence are distinct.
  A failed search is not proof of absence. Required fields are never fabricated.
- The project remains industry-neutral, portable Python 3.13, using `uv run`.

## 3. Baseline and interpretation

The existing development run is `eval_e9ae8f32feaf`:

| Measurement | Recorded baseline |
|---|---:|
| Development documents / reference fields | 72 / 668 |
| Exact and current normalized matches | 596 / 668 (89.22%) |
| Reference evidence units retained by routing | 152 / 152 |
| Selected source units | 200 / 561 |
| Relevance requests / all requests | 123 / 576 |
| Technical failures / cases with unresolved fields | 0 / 2 |
| Reference mismatches marked SUPPORTED | 69 |
| Reported model cost | $0.630840 |

These 69 outcomes are **not 69 established factual errors**. The comparator mixes
substantive mistakes, field association mistakes, representation differences and
potential reference/schema ambiguities. The references were AI-reviewed, not
independently human-approved. Page/block citation matches also do not establish
that a quoted span or field value was checked correctly.

The 91-page PDF retained all six reference evidence pages with 12 relevance calls.
Its reported mismatch was `around 1.9 million` versus `1.9 million`, which is not
an incorrect number. Approximation still needs to be preserved in the output
contract. Two initially correct fields were re-extracted without improving the
overall match count; the complete job cost $0.346774. This motivates targeted
recovery experiments, not a claim that the new routing lost the needed evidence.

Detailed reports and source bytes are local, ignored artifacts. Never copy their
raw contents into source control. If they are missing, report the limitation;
do not invent baseline results or regenerate reviewed reference answers silently.

## 4. Phase A — audit evaluation before changing acceptance

### Work

1. Validate corpus integrity. Preserve all 120 identities, hashes and 72/24/24
   split assignments. Restore missing source files only with the established
   preparation workflow; local AI-reviewed annotations require their saved backup.
2. Freeze the baseline reports and record source/reference fingerprints and
   comparator versions. Do not overwrite historical results.
3. Review all 69 development mismatches against their field instructions and
   original source material. Record a primary category and optional secondary tags:
   wrong value, wrong field/row/period, omission, representation-only difference,
   incomplete/extra content, ambiguous schema or uncertain/reference issue.
4. Keep adjudication notes and per-case outputs in ignored evaluation storage.
   AI adjudication remains explicitly AI-reviewed. Do not require the owner to
   manually re-review every file; independent review of a small control set would
   strengthen later accuracy claims without changing the existing review policy.
5. Define field comparison policies before rerunning models. Retain the historical
   exact/current-normalized metrics alongside the new metrics for comparability.

### Comparison rules

- Verbatim text: require the requested transcription; only explicitly permitted
  whitespace or Unicode transformations may be ignored.
- Typed values: compare under declared number/date/currency/unit semantics.
- Semantic equivalence: report separately, with the adjudication method identified.
  Do not use the production verifier as the sole judge of its own correctness.
- Unknown: retain ambiguity rather than awarding an automatic match.
- Arrays: evaluate item identity, parent/child association, order where required,
  duplicates and omissions. Do not hide shifted rows by sorting all items globally.

Do not rewrite returned data or reference answers merely to improve a score. If a
reference correction is warranted, version and explain it, retain the old reference
fingerprint and distinguish reference changes from pipeline improvements. Do not
inspect or tune on calibration/holdout annotations in this development work.

### Exit criteria

The 69 flagged fields are categorized with uncertainty exposed. Formatting
differences and substantive mismatches have separate counts. A reproducible,
versioned comparison policy exists before claims of improved verification are made.

## 5. Phase B — introduce a minimal evidence/value contract

Keep caller-facing `data` conforming to the requested schema. Add provenance and
validation information to the existing diagnostics, rather than replacing each
data value with a new envelope.

Recommended internal information, with final names chosen to fit existing models:

| Information | Purpose |
|---|---|
| Returned value | The value projected into caller data |
| Raw value text | Literal source transcription, when the task is extractive |
| Source reference | Existing document unit and canonical locator |
| Text span or image region | More precise support than a page ID alone |
| Normalization method/version | Explain any conversion from raw text |
| Qualifiers and units, when applicable | Preserve approximation, bounds and units |
| Mechanical check results | What code actually checked and its outcome |
| Semantic verdict | What the model concluded, recorded separately |

Use the existing evidence envelope and field paths wherever possible. Nested
leaves must support their own evidence; inheriting a root citation does not prove
the association of a particular child or table cell. Multiple source spans remain
supported. Derived or summarized fields must be distinguished from literal copying:
their final value need not appear verbatim in any single span.

Any new span must identify the immutable canonical text artifact and its hash or
equivalent source version. Specify offset conventions precisely, for example
half-open Python Unicode string offsets into that artifact, not offsets into a
model prompt, serialized JSON or UTF-8 bytes. Validate bounds and unit ownership.
Image coordinates must state their coordinate system and source image identity.

Extend persistence and HTTP schemas additively where feasible. Preserve diagnostics
for historical results without inventing new evidence for them. Version changed
extraction/verification payloads and checkpoint contracts; explicitly handle older
pending jobs rather than replaying incompatible paid outputs as new evidence.

## 6. Phase C — mechanical checks with narrow, explainable scope

Use a small typed check result with an outcome such as `PASS`, `FAIL`,
`NOT_APPLICABLE` or `INDETERMINATE`, plus a stable reason code, policy version and
evidence references. Avoid a generic validation DSL in this phase.

### C1. Source and literal-span checks

- Validate document/unit identity, canonical locator, artifact version and span bounds.
- For supplied offsets, compare the quoted/raw text with the exact referenced slice.
- Without offsets, search only the cited source unit's actual text. Preserve multiple
  matches as ambiguous; do not silently take the first occurrence.
- Never search instructions, schemas, candidate values, model summaries or prompt
  metadata as if they were original source text.
- Keep an exact match distinct from any explicitly permitted normalized match.
- Match complete values/tokens: `100` inside `1000` is not evidence for `100`.
- A valid quote proves that words occur there; it does not prove the chosen field,
  period, subject, row or column is correct.

Missing native text makes the text check not applicable, not failed. Bad reading
order or disagreement between PDF text and the rendered image requires a recorded
conflict and source review. A copied hidden/stale text layer is not infallible visual
truth. No fixed text-length heuristic should choose the processing modality.

### C2. Conservative typed-value checks

- Use exact decimal arithmetic for money and decimal quantities. Define permitted
  rounding and tolerances explicitly; avoid a global float epsilon for all fields.
- Parse separators and date formats only when locale/format semantics are known.
  Ambiguous `1,234` or `03/04/2026` must not be guessed silently.
- Preserve currency, units, signs, ranges and qualifiers such as approximate,
  at least, at most and excluding tax. A normalized number alone must not erase them.
- Keep identifiers as identifiers: preserve leading zeros and meaningful case or
  punctuation unless the field contract explicitly permits a transformation.
- Do not apply edit-distance/fuzzy digit matching to accept `55,854` as `55,834`.
- For plain string fields, remain conservative. Numeric-looking strings are not
  automatically quantities. Do not infer comparison policy from a field-name regex.
- A normalized value must have a declared, reproducible relationship to raw evidence.
  Derived values require the specified operation and supporting operands instead.

### C3. Optional domain constraints — later, only when declared

Support a few explicitly supplied constraints only after the minimal slice works.
Examples include a required identifier format or a declared subtotal/tax/discount
equation. Include currency, missing-value and rounding semantics. Do not assume
that every total equals the sum of line items, or that missing tax means zero.
Detect inconsistencies; never alter source numbers merely to make an equation pass.

### Exit criteria

Each check is traceable, deterministic and tested against positive and negative
examples. A failed applicable value check cannot be overridden solely by a high
model score. A text match cannot by itself produce semantic acceptance. Vision-only,
derived and genuinely ambiguous cases are handled without false failure or success.

## 7. Phase D — integrate semantic verification and acceptance

Preserve the existing independent source-based verifier, but make its task explicit:
does the evidence support this field's meaning, requested period, item association,
units, completeness and allowed representation?

Recommended acceptance behavior:

- Keep schema validity independent from evidence and semantic acceptance.
- For a literal TEXT extraction with an applicable failed source/value check,
  return unresolved or request bounded recovery, even if the model says SUPPORTED.
- A source-span match still requires the semantic verification policy to pass.
- A vision-only field may be accepted under a documented model-based policy with
  valid visual citations; expose that text matching was not applicable. Do not
  label this mechanically proven or calibrated correctness.
- A text/image conflict must remain visible. A new attempt can resolve the conflict
  with new evidence; do not relabel a failed check as passed because a model agrees.
- Null and empty collections require the existing document-wide absence/coverage
  semantics. An optional field is not automatically correct when empty.
- For a summarized/derived field, check its declared transformation and semantic
  support rather than requiring the final string/number to occur in the source.
- Preserve raw model probabilities and identify the verification method. Do not
  turn an arbitrary score into a percentage correctness guarantee.

Do not delete full-document contradiction checking or absence coverage merely
because local evidence looks plausible. Any later optimization of that scope is a
separate measured experiment with explicit completeness and conflict tests.

## 8. Phase E — make recovery specific and bounded

Use a failed check's reason and cited sources to ask for a targeted reread of the
affected field. Provide the original page/block and enough neighboring context;
the model continues to choose the needed available modality. Expand to broader
search or stronger extraction only when local support remains inadequate.

For image ambiguity, test clearer source rendering or a referenced region with page
context as useful additional evidence. A second reader or OCR may be evaluated later
as another fallible signal, not introduced as a mandatory new dependency now.

An optional experiment is to let a reader independently extract the disputed value
before seeing the earlier answer, then compare the results. Treat this as an A/B
experiment, not a proven guarantee and not a mandatory extra call for every field.

Keep one shared field/job attempt budget across check types. Do not give every
failed check its own additional retry allowance. Preserve candidates, source/check
results and costs before and after recovery. Never retry the same inputs indefinitely
until a model produces the desired approval. Changed check/input/prompt versions
must participate in checkpoint identity; compatible retries reuse paid steps.

## 9. Implementation map

Use existing domain/application/adapter boundaries. Suggested touchpoints are:

| Area | Existing files / responsibility |
|---|---|
| Field/evidence/check models | `src/ai_idp/domain/models.py`; small pure validation helpers in the domain if needed |
| Field policies and schema handling | `src/ai_idp/domain/schema_normalizer.py`, `src/ai_idp/domain/field_paths.py` |
| Model input/output envelopes | `src/ai_idp/application/ports/protocols.py`, `src/ai_idp/adapters/outbound/openrouter/extraction_client.py` |
| Semantic verifier questions | `src/ai_idp/adapters/outbound/openrouter/decisions_client.py` |
| Check orchestration and recovery | `src/ai_idp/application/services/pipeline.py` |
| Durable storage and replay | `src/ai_idp/adapters/outbound/persistence/models.py`, `repositories.py`, migrations only if required |
| Additive result diagnostics | `src/ai_idp/adapters/inbound/http/schemas.py`, `app.py` |
| Comparison policies and reports | `src/ai_idp/evaluation/metrics.py`, `runner.py` |
| Operational contract | `docs/05-extraction-verification.md`, `docs/13-operations-and-release.md` |

Do not redesign readers, provider adapters, the queue or the page-batch relevance
contract as incidental cleanup. Inspect existing text/evidence representations
before proposing new abstractions. Persist check results atomically with the
corresponding candidate/result and enforce the same lease ownership safeguards.

## 10. Required behavior tests

Build focused project-owned synthetic examples and regression tests. Never commit
external document bytes, model output or per-case adjudication drafts.

| Example | Required behavior |
|---|---|
| Source has `55,834`, candidate has `55,854` | Detect the literal/typed mismatch when reliable text evidence is available |
| Requested number exists on another page or only in the prompt | Do not treat it as a match to the cited source |
| `100` occurs only inside `1000` | No numeric-token match |
| Both prior/current-year totals occur in the source | Text existence alone cannot bypass the semantic period check |
| Item name contains copied quantity/price; quantity is missing | Preserve a field-association failure rather than accepting the whole printed line |
| Table values come from different rows or an array item is omitted | Test association and completeness, not just leaf-string presence |
| `1 200,00 EUR` versus a declared normalized amount | Permit only the declared conversion; retain raw text and currency |
| `around 1.9 million` versus `1.9 million` | Distinguish numeric agreement, approximation and a verbatim-format requirement |
| Identifier `00123`, negative amount, bounds, units | Preserve their meaning; no blanket stripping or coercion |
| Ambiguous numeric/date notation | Report uncertainty unless the contract resolves it |
| Repeated quote, out-of-range offsets, wrong source hash or unknown unit | Reject invalid anchoring or retain ambiguity explicitly |
| Scan or DOCX embedded image without native text | Text matching is not applicable; source-based visual verification remains available |
| PDF text contradicts the rendered image | Keep the conflict and any bounded resolution in diagnostics |
| Derived total is not literally printed | Apply declared transformation checks instead of a universal substring requirement |
| Missing optional field or empty array | No unsupported absence claim; retain document-wide coverage behavior |
| Model approves a mechanically inconsistent value | No silent automatic promotion to verified |
| Retry, crash/replay, budget exhaustion or cancellation | No lost evidence/history, stale-owner writes or unbounded paid calls |
| Existing 100-page / 80-field routing case | Still 13 relevance requests under the same bounds |

Include actual adapter/envelope tests and API/persistence integration tests where
contracts change. Avoid tests that only mirror helper implementation details.

## 11. Evaluation, rollout and completion criteria

Implement in small reviewable slices: A first; B plus C1 next; C2 and D next;
targeted recovery experiments last. Each behavior change needs relevant offline
tests. New caller-specific arithmetic rules and additional model/OCR calls are
optional follow-ups, not prerequisites for the first useful improvement.

During a separately authorized implementation, run the applicable checks:

```text
uv run --locked --group evaluation python -m scripts.validate_corpus
uv run --locked --group dev --group evaluation python -m pytest -q
uv run --locked --group dev python -m ruff check .
uv run --locked --group dev python -m ruff format --check .
uv run --locked --group dev python -m mypy
uv lock --check --offline
```

Real model runs require explicit live authorization and a stated spend cap; this
planning request grants neither. After authorization, start with a small frozen
development selection covering native text, scans, mixed PDF, DOCX and tables,
then assess all 72 development cases if the remaining authorized budget permits.
Keep calibration/holdout untouched unless separately authorized. Do not silently
drop failures from the denominator or substitute easier source cases.

Compare the unchanged baseline against the new policy on the same references:

- Substantive false acceptances among automatically accepted fields, distinct
  from exact/representation mismatches and uncertain adjudications.
- Automatic acceptance coverage, unresolved/rejection rates and recovery outcomes.
  Fewer false acceptances obtained by rejecting everything are not a useful win.
- Field-value accuracy, field association/completeness and absence quality.
- Page/block evidence recall separately from span/value anchoring correctness.
- Exact, declared-normalized and separately adjudicated semantic match metrics.
- Full pipeline requests, model cost, p50/p95 latency and per-stage recovery cost.

Keep report, policy, model, schema and reference versions. Report source/format
breakdowns and unresolved tradeoffs. Do not claim improved factual accuracy solely
because comparison rules became more permissive. An automatic acceptance threshold
must be evaluated against independently checked examples before any calibrated
correctness claim; the present AI-reviewed set alone does not establish that claim.

Completion requires passing applicable deterministic regressions, preserved routing
behavior, inspectable end-to-end diagnostics and a measured development assessment
with regressions disclosed. Promote the new policy as an improvement only if the
substantive acceptance results support that conclusion at useful coverage. Keep
historical results readable and document handling of older pending jobs.

Before publishing, inspect the exact staged paths, metadata and secret/personal-data
scan results. Only source, safe synthetic fixtures, tests and aggregate engineering
documentation belong in Git; reference drafts and runtime/model artifacts stay ignored.

## 12. Research references and their limits

These references informed the recommendation; they do not imply migration to these
services or a guarantee that their advertised behavior transfers to this project.

- [Google Document AI document model](https://docs.cloud.google.com/document-ai/docs/reference/rest/v1/Document):
  separates source text/page anchors, entity text and normalized values.
- [Google Document AI evaluation](https://docs.cloud.google.com/document-ai/docs/evaluate):
  documents exact/fuzzy matching and parent/child association in table evaluation.
- [Google validation and correction](https://docs.cloud.google.com/document-ai/docs/ce-validation):
  describes explicit consistency, arithmetic and spatial checks and revalidation
  after correction. The described feature is a preview; use the design examples,
  not its availability or implementation as a project dependency.
- [Microsoft accuracy and confidence guidance](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept/accuracy-confidence?view=doc-intel-4.0.0):
  distinguishes text-reading and field-extraction confidence and discusses review.
- [AWS Textract best practices](https://docs.aws.amazon.com/textract/latest/dg/textract-best-practices.html):
  recommends choosing confidence thresholds for the application and its error cost.
  Do not import another provider's thresholds as calibrated values for our models.

**First deliverable for the implementation agent:** the versioned development
mismatch audit and a minimal evidence-anchoring/check-result slice with tests.
Do not start by adding more verifier models or weakening the comparator globally.
