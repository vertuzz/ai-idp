# 04 — AI Decision Pipeline

## Main principle

The decision model owns **content-dependent** relevance and extraction-strategy choices. Native text, rendering, metadata, and schema descriptions are input signals. No heuristic such as 'less than 50 characters implies VISION' is part of the initial experiment.

The first implementation should directly test whether the chosen OpenRouter decision model supports the intended combination of image state, text, metadata, question batching and response probabilities in its current API revision.

## Stage A: page-batch relevance for the complete field set

Each request receives a bounded group of source units (PDF pages, DOCX blocks or
image frames), their available images and native/semantic text, the **complete**
requested field set with descriptions and nested schemas, and caller instructions.
Required and optional fields are both search targets. Source content outside the
batch is not concatenated into these relevance requests.

The classifier answers **one yes/no question per unit**: can this named unit directly
provide or materially clarify at least one requested value? Other units supply context,
not evidence that makes an unrelated candidate relevant. Headings, table continuations
and visual-only evidence can make a unit relevant. This is not document-type classification.

The output is one relevance probability per unit, not a unit/field matrix. All fields
share the selected source set for extraction; field-level evidence and verification
remain separate downstream steps.

### Selection policy

- Preserve the classifier's original probability vector for each unit.
- Select units at or above `RELEVANCE_THRESHOLD` (default 0.35).
- Retain at least the document-wide top `RELEVANCE_TOP_K` units (default two) as a
  safety floor, using source order for equal scores. There is no per-field top-K map.
- Missing fields still receive bounded recovery over all source units, including
  pages below the relevance threshold. Selection is not permanent deletion.
- Scores and thresholds are routing parameters, not calibrated correctness guarantees.

## Stage B: extraction modality

For each selected unit / field-group, classify:

- TEXT: use native extracted text or semantic HTML.
- VISION: use a rendered page or source image.
- TEXT_AND_VISION: use both text/HTML and the image.

These are not assertions that every page needs exactly one transformation. DOCX without faithful page rendering may have only semantic text and embedded pictures; its available modalities must be declared to the model. If a requested modality is not available, record a capability limitation and escalate or return unresolved rather than silently substituting an unrelated input.

A multimodal LLM can still be used for text-only extraction by providing text and no image.

## Decision API contract

Use OpenRouter Decisions API (`POST /api/alpha/decisions`) through a dedicated httpx adapter, with typed Pydantic request and response validation. Keep provider-specific question types (`noul`, `choice`, `score` with explicit `criteria`) out of the domain interfaces; normalize to typed probability decisions.

A model may accept multiple named questions about one state, but batching can change accuracy. Benchmark one unit question per call versus grouped unit questions, especially for the smaller Flash variant.

Pipeline v4 implements this page-batch contract. The default
`RELEVANCE_STRATEGY=decisions` uses `AI_IDP_DECISION_MODEL`
(`perplexity/pplx-decider-v1.2`) and one named `noul` question per unit. A relevance
decision has `field_path=null` and version `v4-page`; its field scope is the complete
extraction specification. The final routing checkpoint stores ordered unit IDs,
`unit_scores`, threshold and the document-wide safety floor.

`RELEVANCE_BATCH_UNITS=8` and `MAX_DECISION_IMAGES_PER_CALL=8` are the defaults.
Live boundary checks on 2026-10-18 accepted eight images with 80 field descriptions,
with and without native text. Nine, ten, twenty and fifty images were rejected by
the configured provider with `At most 8 images are allowed per question`. Thus a
100-page PDF with one image per page and 80 fields needs **13 relevance requests**,
provided byte limits do not split groups further. This count excludes later modality,
extraction, verification, recovery and HTTP retries. Count all embedded DOCX images:
a block with multiple images uses multiple image slots, and text-only blocks use none.

`MAX_DECISION_QUESTIONS_PER_CALL=24` now bounds **unit questions**, not unit/field
pairs. The complete field set is included in every group and is never divided into
additional relevance calls. Byte and image limits can reduce group size. A single
unit or complete request exceeding supported limits fails explicitly; no text,
image or field description is silently discarded.

`MAX_PARALLEL_DECISION_BATCHES=8` bounds relevance workers and selected-unit modality
workers within a job. Shared global/per-model capacity, rate limits and job-wide
physical request budgets still apply. Completed groups are checkpointed individually;
progress counts completed units and source order is independent of completion order.

The alternative `RELEVANCE_STRATEGY=generative` returns one boolean/null flag per
unit ID for the same complete field set. `true` is relevant, `false` is clearly
irrelevant, and `null` is uncertain and retained. The response must contain every
requested unit with the correct types. These flags have no probability vector and
are never presented as calibrated confidence. Field verification remains with the
separate decision model.

For a sequential single-unit comparison, set `RELEVANCE_BATCH_UNITS=1` and
`MAX_PARALLEL_DECISION_BATCHES=1`. `--unbatched-questions` also means one **unit**
question per relevance request, still carrying all fields. Compare the same development
cases and references, including evidence recall rather than request count alone.
Historical v3 reports measure a different relevance contract. Pending v3 jobs fail
explicitly on a v4 worker and must be resubmitted; old checkpoints are not reinterpreted
as page scores. Completed historical results remain inspectable.

Persist: model ID, provider API version, question set/version, state artifact IDs/hashes, probability distribution, chosen option, latency, usage where available, failure status and retry count.

## Failure and uncertainty

- Invalid/partial decision responses: bounded retry with backoff.
- Missing answers, invalid probabilities and inconsistent choices fail explicitly; they never default to a positive verification result or an invented probability vector.
- Do not truncate source text, candidate values, quotes or document context by character count. Provider context errors remain explicit failures.
- Rate limiting: requeue with delay rather than busy-loop.
- Low confidence or disagreeing signals: preserve multiple candidates.
- Model unavailable: record failure and stop or use an **explicitly configured** backup model; never silently change providers.
- No decision is a permanent source of truth; validation and independent evaluation remain mandatory.

## Initial candidates

Primary decision-model baseline: `perplexity/pplx-decider-v1.2` via OpenRouter (verified with multimodal text+image state and batched `noul`/`choice` questions). Comparison candidates may include `perplexity/pplx-decider-flash-v1.2` and other compatible decision models (`typesafe/jev-1.14`, `liquid/d1-ultra`, `openai/gpt-6-luna-decisions` or future models) after checking API availability and capabilities.

Treat availability, licensing, image support, context limits and pricing as time-varying configuration facts; measure instead of assuming benchmark superiority.
