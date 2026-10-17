# 05 — Structured Extraction, Verification, and Recovery

## Extraction

The caller submits a JSON Schema. Normalize it to named target fields or paths (including nested objects and arrays), descriptions, types and optional semantics. The extraction adapter invokes a configurable OpenRouter generative model via Pydantic AI (default primary baseline: `anthropic/claude-haiku-5.5`).

- Group related fields and candidate units to retain context (such as tables spanning pages).
- Use selected TEXT, VISION or TEXT_AND_VISION inputs.
- Ask the model for field values, source references and short supporting evidence.
- Validate shape/types against the caller schema; keep an internal envelope with evidence separate from the final clean JSON value.
- Normalize obvious scalar representations only when supported by schema semantics; never create unsupported financial/other values.
- Treat an unavailable value as null/unresolved in the internal result, even if the final caller schema requires a non-null value; report schema completeness explicitly.

Example internal field candidate:

~~~json
{
  "path": "/annual_revenue",
  "value": 1250000,
  "sources": [
    {
      "unit_id": "unit_000012",
      "locator": {"page_number": 12},
      "quote": "Annual revenue: 1,250,000"
    }
  ],
  "extraction_model": "anthropic/claude-haiku-5.5",
  "attempt": 1
}
~~~

For arrays, field identity may include item paths and each item may reference a different source.

## Independent field verification

Verify **against source material**: original text or rendered image, relevant schema description, extracted candidate and evidence locators. Do not simply re-check a generative model's own summary.

Prefer a three-way decision:

- SUPPORTED: evidence supports the specified value and its semantic meaning.
- CONTRADICTED: evidence conflicts with it.
- INSUFFICIENT_EVIDENCE: evidence is ambiguous, missing or too weak.

Record the complete raw probability vector and model/version. A score such as 0.95 for SUPPORTED is *not* a calibrated 95% correctness probability. Calibrate on held-out human-labeled examples before exposing any derived calibrated confidence. An optional aggregate confidence must clearly say how it was computed.

Do not conflate a missing field with a hallucination. Missing, contradicted, and uncertain require different recovery actions.

## Escalation state machine

1. Extract initial field candidates using selected modality and candidate units.
2. Verify each populated candidate independently.
3. If unsupported/uncertain, retry the **specific field** with original source and richer modality or neighboring context.
4. If needed, use a configurable stronger extraction model (default escalation baseline: `google/gemini-4-argon`); re-verify the replacement value.
5. For fields still missing, run coverage review over previously unselected/low-score units and attempt relevant extraction.
6. After bounded retries, return UNRESOLVED with reason and evidence trail; never silently promote uncertainty to success.

Suggested defaults: at most two additional field extraction attempts after the initial attempt, one missing-field coverage review, and a configurable job-level total-call / spend / wall-clock budget.

## Result contract

Two layers:

1. **Data:** an object intended to conform to the caller JSON Schema where evidence is sufficient.
2. **Diagnostics:** per-field source references, verification state, raw decision scores, attempts, model identifiers, missing reasons and cost.

For a required field that cannot be verified, either expose a documented partial-result state with internal null or return a schema-validity error/partial result. Do not fabricate a schema-compliant non-null value.

## Validation details and limitations

- Validate data types and required properties independently from semantic truthfulness.
- Deterministic arithmetic/string checks may be useful as **validation**, but the MVP does not use deterministic content heuristics to decide a parsing route.
- Extracting value and verifying it with related models can produce correlated errors. Independent prompts and source access help but are not guarantees.
- For a field supported by multiple source units, verification must consider all relevant evidence.
- Store the original and every replacement candidate with reason, chronology and cost.
- Never label raw decision-model probabilities as guaranteed confidence or a probability of no hallucination.
