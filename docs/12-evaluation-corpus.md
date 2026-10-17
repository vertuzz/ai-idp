# 12 — Evaluation Corpus: 120-Document Pilot

**Status:** approved target design; all 120 candidate files are now acquired. Fifty cases have draft answer keys; 70 still require field annotation. Human review, final rights/group adjudication and benchmark freeze remain pending. See the [actual corpus catalog](../eval/CORPUS.md). This document remains the authoritative preparation policy.

The initial evaluation corpus must be prepared **before substantial application implementation**. It will drive development with real examples rather than post-hoc benchmarking. The project remains public, Apache-2.0-licensed, general-purpose and potentially suitable for future commercial services. Source datasets retain their **own** licences.

## 1. Frozen target composition

| Source | Documents | Typical form | Main evaluation purpose |
|---|---:|---|---|
| [DocLayNet](https://huggingface.co/datasets/docling-project/DocLayNet) | **35** | Real single-page PDF + corresponding image / structural annotations | PDF-native text vs visual layout, tables, figures, decision modality |
| [CORD v2](https://huggingface.co/datasets/naver-clova-ix/cord-v2) | **30** | Real receipt images + reference annotations | Vision extraction, numeric fields, nested line items, verification |
| [UK government PDFs](https://www.gov.uk/government/publications) | **20** | Real multi-page PDF reports, guidance, forms | Page relevance, context across pages, irrelevant pages, missing fields |
| [UK government DOCX](https://www.gov.uk/government/publications) | **15** | Real Word templates/forms/docs | Mammoth semantic block processing, tables, embedded assets, field-to-block provenance |
| **Synthetic realistic stress documents** | **20** | PDF, DOCX and images produced by project-owned generators | Controlled ambiguity, negative cases, multi-page continuations, scan artifacts, extraction escalation |
| **TOTAL** | **120** | | |

A preliminary **400–700 pages/logical units** is a planning estimate, **not a fixed quota**: the true count is determined by the documents eventually selected. Multi-page originals must be evaluated in full even if the estimate is exceeded, subject to configured compute budgets.

**Document-count semantics:** a DocLayNet one-page PDF counts as one document; a CORD receipt counts as one document; a government PDF/DOCX counts as one source file regardless of length; a synthetic stress file counts as one document. Alternate renderings of the same source do **not** count as additional documents. Generated negative/counterfactual questions do **not** count as documents.

**Important scope caveat:** DocLayNet provides annotated page layouts, **not arbitrary extraction-question ground truth**; the selected pages still need project-specific field/value/evidence labels. Government documents likewise require manual or human-reviewed annotations. CORD labels are a starting point, but the evaluation schema and item mapping must be checked.

## 2. Dataset sources and rights

### DocLayNet (35 documents)

- Official page: https://github.com/DS4SD/DocLayNet
- Dataset: https://huggingface.co/datasets/docling-project/DocLayNet
- Published dataset licence: **CDLA-Permissive-1.0**; see https://cdla.dev/permissive-1-0/
- Assets described upstream: page PNGs, human layout annotations, optional one-page PDFs and digital-text/coordinates JSON.
- Cover all six source categories if feasible: financial reports, scientific articles, laws/regulations, government tenders, manuals and patents.
- Prefer original single-page PDFs **and** corresponding images for faithful TEXT vs VISION comparisons. If the exact selected sample lacks the PDF artifact, explicitly mark that limitation instead of claiming text-vs-vision equivalence.
- Preserve original document identities so pages from the same underlying source cannot straddle development/calibration/holdout splits.
- Verify per-item redistribution conditions before committing any original PDF/image; treat upstream licences and embedded third-party material as separate rights checks.

### CORD v2 (30 documents)

- Official project: https://github.com/clovaai/cord
- Dataset: https://huggingface.co/datasets/naver-clova-ix/cord-v2
- Published licence: **CC BY 4.0**. Attribution is required; see https://creativecommons.org/licenses/by/4.0/
- Choose genuine receipt images across diverse layouts, small print, long item lists and ambiguous totals.
- Adapt available labels into our target schemas without falsely treating every annotation field as a universally meaningful extraction field.
- Track original split and dataset revision/commit; do not inadvertently tune against a reserved upstream test subset.

### UK government documents (20 PDFs + 15 DOCX)

Potential discovery locations (not a pre-approved list of 35 exact assets):

- https://www.gov.uk/government/publications/explanatory-memorandum-template-and-guidance — Word template and PDF guide.
- https://www.gov.uk/government/publications/managing-public-money-framework-documents — multi-page PDF guidance and multiple Word templates.
- https://www.gov.uk/government/publications/financial-remedy-summary-of-case-form-es1 — a Word document, subject to document-specific rights and suitability review.
- https://www.gov.uk/government/publications/managing-public-money — public-sector finance documents.
- Other suitable and licence-checked official government publications to diversify document purpose, length, layout, and style.

**Rights gate:** much UK public-sector information is available under [OGL v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/), which permits commercial reuse with attribution, but **not everything on GOV.UK is automatically covered**. Check the actual publication, any attachment notices, third-party elements, personal information, logos and additional restrictions per file. Record a source-specific attribution statement. Do not copy files with unclear rights into the public repository.

Select reports and forms that expose questions with objectively checkable answers, such as section titles, effective dates, numerical thresholds, organization names, totals and table cells. Never add answers merely because they sound plausible.

For DOCX, ground truth refers to **semantic block IDs**, heading paths and content excerpts, not imaginary physical page numbers. Test information that semantic conversion may omit (e.g., drawings, headers/footers) by recording capability limitations.

### Synthetic realistic stress documents (20 documents)

Create using original project-controlled templates and realistic but **fake** names, addresses, figures and identifiers. Tools used to **generate evaluation fixtures** (such as python-docx, ReportLab and Faker) do not imply runtime dependencies for extraction.

Proposed stress diversity:

- 5 native-text PDFs with tables, conflicting years/currencies and long contextual distractors.
- 5 scanned/rasterized PDFs or image-based documents with noisy typography, skew, blur or rotated content.
- 5 DOCX files with semantically rich tables, headings, embedded pictures and problematic layout.
- 5 multi-page mixed-content PDFs with answer continuations and missing/contradicting values.

Ground truth should be generated deterministically from template parameters then human-reviewed. Avoid copying proprietary layouts or real personally identifying details.

## 3. Split policy: 72 / 24 / 24

Freeze selection and split membership before prompt/threshold optimization.

| Source | Development | Calibration | Holdout | Total |
|---|---:|---:|---:|---:|
| DocLayNet | 21 | 7 | 7 | 35 |
| CORD v2 | 18 | 6 | 6 | 30 |
| Government PDF | 12 | 4 | 4 | 20 |
| Government DOCX | 9 | 3 | 3 | 15 |
| Synthetic | 12 | 4 | 4 | 20 |
| **Total** | **72** | **24** | **24** | **120** |

- **Development:** iterative prompt, architecture and pipeline changes.
- **Calibration:** threshold selection, score calibration, model selection trade-offs.
- **Holdout:** final, infrequent unbiased comparison; never tune against this split.
- Stratify by source, file format, document complexity and length. Group near-duplicates, pages from the same original, templates and document families **before splitting** to avoid leakage. Source-group leakage prevention overrides the count targets if necessary, with deviations documented in the frozen manifest.
- Retain official upstream train/validation/test distinctions in provenance and choose a nonleaking mapping compatible with upstream constraints.

## 4. Per-document ground-truth requirements

A selected file becomes an **evaluation-ready case** only after passing annotation review. For each document:

1. Stable local case ID; source dataset/publisher and immutable original URL or upstream ID.
2. File type, SHA-256, source revision/download timestamp and asset-to-document mapping.
3. Source licence, attribution, commercial-use status, redistribution status, third-party/privacy review and rights approval.
4. Frozen suite split; source group / duplicate-group identifier.
5. At least one caller-like JSON Schema with clear field descriptions and extraction instructions; aim for 3–8 scalar/structured extraction targets per case as feasible.
6. Ground-truth field values with types, units, periods and permitted normalization rules.
7. Every answer's source page(s)/semantic block(s), supporting short quotation/cell coordinate, and explicit missing/absent labels where relevant.
8. Independent annotation review for ambiguous cases; document adjudication/uncertainty rather than forcing a false certainty.
9. Feature tags such as scanned, native_text, mixed, multi_page, table, handwriting, poor_image, cross_page, missing_field, ambiguous.
10. Known conversion limitations, especially DOCX, and evaluation exclusions if any.

Use JSON Pointer-style field paths for nested objects and arrays. One field may cite **multiple** source units. Both a first-pass value and its supporting evidence must be evaluated independently.

Important: a dataset's existing OCR/layout labels do not necessarily establish field correctness. Human-reviewed field-level evidence is the source of truth.

## 5. Evaluation questions and experiment matrix

### A — Relevance selection

For each schema field: were all required evidence units selected? Record page/unit recall, missing evidence, shortlist length, candidate rank and fraction processed. Evaluate negative/irrelevant pages using the original full multi-page file, not an artificially isolated page.

### B — TEXT vs VISION vs BOTH

Run matched extraction tests with available native text, rendered page image, and combined inputs. Record field accuracy, failure modes, and **full stage costs**, not agreement with an arbitrary single 'correct modality'. More than one strategy may be valid.

### C — Structured extraction

Measure normalized field accuracy, nested array/line-item accuracy, missing-value accuracy, schema validity, and source citation correctness on the caller-like schemas.

### D — Independent verification / hallucination resistance

Construct deterministic counterfactual **field candidates** from verified ground truth, without creating extra documents: small numeric changes, digit swaps, shifted dates, wrong units, values from nearby rows/pages, plausible invented items, and incorrect period labels. Label:

- SUPPORTED — value and semantics match evidence.
- CONTRADICTED — presented evidence conflicts.
- INSUFFICIENT_EVIDENCE — referenced evidence cannot establish truth.

Always include real correct candidates and genuine insufficient-evidence examples. Prevent label leakage from test-generation metadata into decision prompts. Measure false acceptance of wrong fields, false rejection of true fields, and distinction between contradicted and unsupported.

### E — Recovery / escalation / coverage

Intentionally test missed-page scenarios, absent fields, multi-page references and low confidence. Track whether the coverage review retrieves initially omitted evidence, whether the stronger model actually corrects values, and incremental cost.

### F — Baselines and ablations

- Always-vision extraction over all source units (without relevance filtering).
- Text-only when text exists.
- Proposed decision-led relevance + modality extraction.
- Proposed pipeline with verification disabled.
- Proposed pipeline with verification, coverage, escalation.
- Compare configurable decision models, extraction models, grouped vs ungrouped decision questions.

Both outputs and expenses must include preprocessing/rendering where relevant, routing calls, extraction, verification, failed attempts, retries and recovery. Compare identical inputs, schemas and splits with frozen versioned configurations.

## 6. Metrics and initial target hypotheses

- Evidence-unit recall (priority metric; routing false negatives are expensive).
- Evidence citation accuracy and hallucination-verifier false-acceptance rate.
- Normalized field accuracy, abstention quality and missing-field detection.
- Field-level verification confusion matrix and (where valid) calibration/Brier score.
- Completeness, schema validity, nested-structure/line-item correctness.
- Cost per document and per verified field; latency p50/p95.
- Failure and escalation rates, model call count, token/image usage.

Initial **hypotheses, not guarantees**: achieve at least 95% of always-vision field accuracy while reducing end-to-end model spend by 30%; set a separate strict false-acceptance budget once pilot ground-truth error distributions are measured.

Report source-specific metrics; do not let easily scored CORD receipts hide a routing regression on government multi-page documents.

## 7. Execution order — evaluation before implementation

1. Establish source licences, download methods and an approved source inventory.
2. Select **20–30 diverse preview cases** from the planned 120 to support early real-model smoke tests. Record actual case IDs instead of inventing them.
3. Freeze 120 chosen document IDs and split membership in a versioned **manifest** with hashes, provenance, licence status and annotation status.
4. Add human-reviewed schemas, values and evidence locators; validate the entire corpus.
5. Build and run model/provider capability smoke tests against the preview cases.
6. During implementation, rerun development split after relevance, modality, extraction and verification changes.
7. Tune thresholds and probability calibration on calibration split only.
8. Run holdout comparison infrequently, with a frozen experiment configuration and archived metrics.
9. Add new datasets later through a separate, versioned corpus release; do not silently replace pilot samples.

**Current project status:** all 120 candidate source identities and files exist, with SHA-256,
provenance and proposed 72/24/24 splits. Fifty draft annotations and 70 annotation work items
are available locally. No reviewed ground-truth suite or real benchmark results are claimed.

## 8. Public repository and legal policy

- Code and original project annotations are Apache-2.0-licensed where copyright applies; upstream source files retain their own licence.
- Keep large upstream binaries out of git by default; publish reproducible retrieval scripts, hashes, manifest and licence/attribution references.
- Redistribute each external source asset only after checking that its precise licence and third-party contents permit redistribution. Link/download on the developer's machine otherwise.
- Dataset access and commercial reuse are distinct questions; record both.
- OGL: preserve attribution and watch exclusions for third-party intellectual property, personal data and official logos.
- CC BY 4.0: retain NAVER CLOVA/source attribution and disclose adaptations where applicable.
- CDLA-Permissive-1.0: preserve licence and provenance as required.
- Generated synthetic documents must not contain secrets, realistic personal identifiers, or confidential source data.
- For source rights not sufficiently established, use them only after review or substitute an approved case without changing target source quotas unless the manifest records the reason.
- Never commit API keys, source documents requiring restricted access, full third-party model responses containing sensitive data, or unreviewed large binaries.

## 9. Optional future benchmark candidates (not part of 120)

- [MP-DocVQA](https://huggingface.co/datasets/rubentito/mp-docvqa): strong multi-page relevance benchmark; review original document/image rights independently of dataset-card metadata.
- [PubTables-1M](https://github.com/microsoft/table-transformer): complex table structures; review the dataset and underlying article reuse rights, not only the repository's source-code licence.
- [DocILE](https://github.com/rossumai/docile): invoice extraction; verify redistribution, access and commercial terms before using.

None of these candidates is implicitly included in the initial 120-document count.

## 10. Source and licence references

- DocLayNet: https://github.com/DS4SD/DocLayNet ; https://huggingface.co/datasets/docling-project/DocLayNet ; https://cdla.dev/permissive-1-0/
- CORD: https://github.com/clovaai/cord ; https://huggingface.co/datasets/naver-clova-ix/cord-v2 ; https://creativecommons.org/licenses/by/4.0/
- UK government: https://www.gov.uk/government/publications ; https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/
- PubTables: https://github.com/microsoft/table-transformer

The upstream licence or terms should be rechecked when downloading and versioned in the frozen manifest.
