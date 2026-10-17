# 09 — Evaluation Strategy

## Central question

Can field-aware decision-model routing reduce the **total** cost and latency of document extraction while preserving output correctness, evidence quality and page/unit recall relative to an always-vision extraction baseline?

The evaluation suite is a first-class MVP deliverable, not a later nice-to-have.

## Dataset

Start with a labeled set of approximately 200–500 diverse pages/units and grow it over time. Include:

- Native-text PDFs, scan-only PDFs, mixed pages and page continuations.
- Simple text, headings, dense tables, multi-page tables, small numeric labels, rotated sections, handwritten elements.
- DOCX with text/tables/embedded images and representative semantic conversion limitations.
- Raster invoices, reports, forms, receipts, contracts and other general-purpose document types.
- Cases with missing values, contradictions, repeated values, ambiguous periods/units and irrelevant pages.
- Synthetic or redistribution-safe documents in the public repository. Keep any private evaluation corpus outside git and out of public CI.

Each case records original source, schema, expected values, acceptable normalizations, field-to-source-unit labels, supported/not-supported annotations and optional valid evidence spans.

## Baselines and experiments

1. **Always-vision:** send all units as images to the extraction model without relevance pruning.
2. **Always-text when present:** basic text extraction, with missing cases marked, as an inexpensive lower-quality comparison.
3. **AI relevance + modality:** proposed decision routing and extraction pipeline.
4. **No verification:** ablate verification to measure impact.
5. **With verification and escalation:** measure final accuracy and retry costs.
6. **Decision model comparison:** Decider V1.2 vs Flash and compatible alternatives; single vs grouped questions.
7. **Extraction model comparison:** cost-focused base model versus stronger escalation model.

Keep identical schemas and datasets for fair comparisons. Record model IDs/revisions, parameters, prompt versions, decisions, usage, provider latency and run timestamp.

## Metrics

- **Page/unit relevance recall:** fraction of required evidence units retained. False negatives are particularly harmful.
- **Precision of selected units:** selected units that were actually needed, plus selection ratio.
- **Field-level exact/normalized accuracy:** evaluated against labeled ground truth.
- **Evidence correctness:** whether cited units and spans truly support the extracted field.
- **False acceptance rate:** unsupported values marked verified; a critical metric.
- **Abstention and missing-field recovery:** correct null/unresolved and successful coverage-review recoveries.
- **Calibration:** reliability diagram and Brier score where decision probabilities can be paired with labels; avoid claiming out-of-the-box confidence calibration.
- **Cost:** observed or estimated all-stage cost per document and verified field, including retries.
- **Latency:** p50/p95 end-to-end latency, time by stage, total tokens and calls.
- **Robustness:** provider/schema failures, context overflow, document conversion warnings.

## Run modes

- Fast unit tests with mocked model interfaces and synthetic documents.
- Opt-in real OpenRouter smoke/evaluation suite using explicit token/spend budgets.
- Reproducible evaluation CLI that emits JSON/CSV/Markdown results and diff against a prior run.
- Public CI uses no real credentials or private fixtures.

Do not optimize thresholds on the same examples used to report final accuracy. Split calibration/development from a held-out test set.

## Preliminary success criteria

Targets are hypotheses, not performance claims: match or exceed 95% of always-vision field accuracy on held-out data while reducing total model spend by at least 30%; hold false-accept verification rates below a separately defined domain risk budget. Revisit targets after first measured baseline and show trade-offs rather than hiding failures.
