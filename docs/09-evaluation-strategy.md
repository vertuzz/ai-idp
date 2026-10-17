# 09 — Evaluation Strategy

## Fixed MVP corpus

The initial **target** is **120 documents**, covering a planning estimate of roughly **400–700 pages/logical units** (not a cap or a guarantee):

| Source | Count |
|---|---:|
| DocLayNet single-page PDFs | 35 |
| CORD v2 receipt images | 30 |
| UK government multi-page PDFs | 20 |
| UK government DOCX | 15 |
| Realistic synthetic stress documents | 20 |
| **Total** | **120** |

The exact source selection, licensing/redistribution checks, annotation conventions, 72/24/24 split, dataset preparation, verification counterfactuals and execution procedure are fully specified in **[12 — Evaluation Corpus](12-evaluation-corpus.md)**. The machine-readable target plan is [eval/corpus-plan.yaml](../eval/corpus-plan.yaml).

**Status: all 120 candidate files and owner-authorized AI source reviews are available.** Development diagnostics use these local references. Independent human benchmark approval, rights and final group adjudication remain separate research/release gates. See the [live corpus catalog](../eval/CORPUS.md) and [AI review scope](15-ai-source-review.md).

## Central research question

Can field-aware decision-model routing reduce **end-to-end** document processing cost and latency while retaining output correctness, source-citation accuracy and page/block evidence recall versus always-vision extraction?

Separate single-page layout/extraction measurements from truly multi-page relevance experiments. Source annotations from DocLayNet are for layout, not automatic answers to the extraction schemas we invent. Real government sources need human-reviewed field labels and evidence locations.

## Test methods

1. **Always-vision baseline:** process all available source units as images, without relevance pruning.
2. **Text-only baseline:** native extracted text when available, with explicit inability/partial results otherwise.
3. **Decision-led pipeline:** field relevance → modality selection → structured extraction.
4. **Verification ablation:** rerun decision-led extraction with and without field verification.
5. **Full recovery:** verification, missing-field coverage review and bounded escalation.
6. **Model experiments:** `perplexity/pplx-decider-v1.2` vs Flash/compatible alternatives; cheap primary extraction (`anthropic/claude-haiku-5.5`) vs stronger escalation (`google/gemini-4-argon`); single-question vs batched decisions.
7. **Modality comparison:** TEXT / VISION / BOTH on the **same** examples, allowing multiple successful strategies.

Use versioned model settings, prompts, schemas and identical frozen splits. Record downstream effects of missed relevance decisions instead of hiding them inside aggregate extraction scores.

## Metrics

- Evidence-unit recall and false-negative page/block routing rate.
- Selected-unit precision and selection fraction.
- Exact/normalized ground-truth field accuracy, missing-value quality, nested array/line-item accuracy.
- Evidence provenance correctness.
- Verification confusion matrix, especially falsely **SUPPORTED** incorrect values.
- Coverage-review recovery and incremental escalation success.
- Where labels permit: score calibration / Brier score; do not treat raw model probabilities as correctness probabilities.
- Full pipeline cost (including decisions, retries, extraction, verification, preparation when billable) and p50/p95 latency.
- Unresolved/failure rates, schema errors and source-conversion limitations.

Report results by source and format as well as in aggregate. CORD’s easy-to-score receipts must not disguise a failure in multi-page routing.

## Evaluation workflow

- **Development split:** 72 documents for repeated iteration.
- **Calibration split:** 24 documents for threshold selection and calibration.
- **Holdout split:** 24 documents for infrequent, unbiased final reporting.
- No source/templated near-duplicate may cross splits. Preserve upstream split metadata.
- Real OpenRouter runs are opt-in, spend-capped and must never be required by normal public CI.
- Local source binaries and large results are downloaded/generated outside git and linked through a manifest of source IDs, URL/revision, SHA-256, licence and annotations.
- Mock unit tests and safe synthetic fixtures remain in CI.
- Produce comparable JSON/CSV/Markdown reports and retain model/provider/version/time metadata.

## Working hypothesis, not a benchmark claim

After freezing ground truth, test whether the decision-led pipeline can match at least 95% of always-vision field accuracy while lowering **overall model cost** by at least 30%. Independently establish a strict limit on false acceptance of incorrect fields. Report actual observations even if the hypothesis fails.

**See also:** [Implementation Plan](10-implementation-plan.md), [Corpus Selection and Licensing](12-evaluation-corpus.md).
