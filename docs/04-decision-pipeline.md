# 04 — AI Decision Pipeline

## Main principle

The decision model owns **content-dependent** relevance and extraction-strategy choices. Native text, rendering, metadata, and schema descriptions are input signals. No heuristic such as 'less than 50 characters implies VISION' is part of the initial experiment.

The first implementation should directly test whether the chosen OpenRouter decision model supports the intended combination of image state, text, metadata, question batching and response probabilities in its current API revision.

## Stage A: field-aware relevance

Inputs:

- Unit image when available; native text/semantic HTML; document/unit metadata.
- Requested JSON Schema and field descriptions, including optional extraction guidance.
- Full native/semantic document text as context, with stable unit IDs, locators and caller guidance. The candidate unit also supplies all of its source images.
- Stable field IDs or JSON paths.

Output: per-unit, per-field (or closely related field-group) relevance scores, uncertainty, optional evidence tags and an overall candidate-unit map.

Avoid a single document-wide boolean. A cover page may matter for document title but not for a balance-sheet value. Table continuations may appear irrelevant without neighboring context.

Suggested decision question: 'Can this unit directly provide or materially clarify the value of field X?' Distinguish direct evidence from contextual relevance where the API makes this practical.

### Selection policy

- Preserve raw probability vectors.
- Keep a configurable relevance threshold **and** top-K fallback for each field/group; do not permanently discard all low-score units.
- Retain ambiguous/continuation units for possible recovery.
- Add an explicit missing-field coverage review after the first extraction pass.
- Thresholds are pipeline selection parameters to be calibrated against labeled data, not indicators of verified correctness.

## Stage B: extraction modality

For each selected unit / field-group, classify:

- TEXT: use native extracted text or semantic HTML.
- VISION: use a rendered page or source image.
- TEXT_AND_VISION: use both text/HTML and the image.

These are not assertions that every page needs exactly one transformation. DOCX without faithful page rendering may have only semantic text and embedded pictures; its available modalities must be declared to the model. If a requested modality is not available, record a capability limitation and escalate or return unresolved rather than silently substituting an unrelated input.

A multimodal LLM can still be used for text-only extraction by providing text and no image.

## Decision API contract

Use OpenRouter Decisions API (`POST /api/alpha/decisions`) through a dedicated httpx adapter, with typed Pydantic request and response validation. Keep provider-specific question types (`noul`, `choice`, `score` with explicit `criteria`) out of the domain interfaces; normalize to typed probability decisions.

A model may accept multiple named questions about one state, but batching can change accuracy. Benchmark one question per call versus grouped field questions, especially for the smaller Flash variant.

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
