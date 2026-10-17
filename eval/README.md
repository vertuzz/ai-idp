# Evaluation corpus

All **120 candidate files** have been retrieved or generated: 35 DocLayNet PDF pages,
30 CORD receipts, 20 government PDFs, 15 government DOCX files and 20 synthetic stress
documents. This is a complete file inventory, **not a reviewed benchmark**.

- [Browse all documents and review status](CORPUS.md)
- [Machine-readable inventory](manifest.jsonl) and [integrity report](corpus-status.json)
- [24-case development preview](preview-selection.json)
- [Corpus specification](../docs/12-evaluation-corpus.md) and [target quotas](corpus-plan.yaml)

## Prepare and validate

Run from the repository root on Windows, Linux or macOS; Windows has been exercised here.
No shell activation, browser login, API key, PostgreSQL or model calls are required.

~~~text
uv sync --locked --group evaluation
uv run --group evaluation python -m scripts.prepare_corpus
uv run --group evaluation python -m scripts.validate_corpus
uv run --group evaluation python -m pytest -q
~~~

Preparation verifies existing assets against the manifest, restores missing originals, and
preserves existing local annotation files. A modified asset fails verification rather than
being silently replaced. `validate_corpus --require-ready` deliberately fails until all 120
cases have reviewed labels; ordinary integrity validation can pass before annotation review.

## Storage and retrieval

- `downloads/corpus/`: ignored original files, original upstream labels and local annotation work.
- `fixtures/synthetic/`: 20 small project-owned fixtures and their parameter files, safe for git.
- `manifest.jsonl`: selected identities, original URLs, revisions, SHA-256, licences, attribution,
  groups, proposed splits and annotation status. This is candidate release v1; final freeze awaits review.
- `*-selection.json`: source acquisition records used to reproduce the candidate selection.
- `cache/`: ignored CORD shards, DocLayNet metadata and optional rendering tools/previews.
- `results/`: ignored future model experiment outputs. No experiments have run.

## What belongs in git

Commit the manifest, source selections, catalog, preview IDs, status snapshot, preparation
scripts, tests, uv configuration and the 20 original synthetic fixtures with their parameters.
External originals, upstream annotation payloads, local draft answer keys, caches, rendered
previews, local renderer binaries and model outputs remain ignored.

After review, store project-authored extraction schemas, expected values and source evidence
in `eval/annotations/`, update their manifest references, and version them with the code.
The current local draft files are not a substitute for committed, reviewed ground truth.
Public metadata may identify upstream publishers and source documents; it must not contain
developer home paths, private account information, credentials or confidential source content.

Before publishing a corpus update, inspect staged paths and contents, including PDF/DOCX
metadata. Only project-owned synthetic PDF/DOCX binaries belong in this initial commit.
The validation report is a preparation snapshot, not a model evaluation result.

The selected originals total 73.2 MiB; counterparts and annotations add more. A clean
acquisition also needs about 1.6 GB of dataset cache: three pinned CORD shards (~967 MB)
and expanded DocLayNet COCO metadata (~665 MB). DocLayNet ZIP members are retrieved using
HTTP ranges rather than downloading both complete multi-gigabyte archives. Cached metadata
supports reproducible page selection and preservation of parent document identities.

CORD uses 18 train, 6 validation and 6 test receipts, mapped to development/calibration/holdout.
DocLayNet uses its corresponding official splits and covers all six categories. Known related
government publications and templates stay together. Obvious receipt-template overlap found
during initial visual selection was removed; further family/near-duplicate adjudication remains pending.

## Annotation state

- **30 CORD cases:** draft JSON Schemas, original amount strings and top-level line items,
  with candidate word-level evidence. Item-to-line mapping and label semantics require review.
- **20 synthetic cases:** parameter-derived answer keys, current-period/old-period distractors,
  deliberately missing purchase-order references, and draft page/image evidence. DOCX semantic
  block IDs still await the ingestion contract.
- **70 DocLayNet/government cases:** annotation work files exist, but schemas, expected values
  and supporting evidence are not yet authored. Layout/OCR labels are not extraction gold.
- **0 cases** are currently marked `evaluation_ready`. Do not publish accuracy/cost claims yet.

The preview selection contains 24 development cases across all five sources, all six DocLayNet
categories, and all four synthetic formats. Review this preview first, then complete the other
96 cases before final benchmark freeze. Do not tune prompts on calibration or holdout cases.

## Rights and verification

Source dataset licence references and publisher attribution are recorded per case. External
originals remain local: file-specific exclusions, third-party material and privacy review are
pending. Apache 2.0 code licensing does not replace CDLA, CC BY or applicable OGL terms.

All primary files were checked for SHA-256, byte size and parseability; PDFs retain complete
source files. The 20 synthetic fixtures were rendered for visual inspection. LibreOffice was
used only as a local development QA tool; it is not an extraction runtime dependency.

## Curation tools

`discover_government_sources`, `acquire_government`, `acquire_cord`, `acquire_doclaynet`,
`generate_synthetic_corpus` and `assemble_corpus` are curation commands under `scripts/`.
Use the fixed candidate manifest with `prepare_corpus` for normal restores; do not rerun
discovery to silently replace selected sources. Generation requires Poppler for raster fixtures.
Synthetic originals are already included in the repository, so normal restore needs no renderer.

The earlier five-receipt starter remains available through `scripts/prepare_cord_preview.py`;
it is separate from the 120-case inventory and adds no extra benchmark documents.
