# MVP engineering validation — 2026-10-17

Follow-up: the owner authorized AI source review after this engineering snapshot.
All 120 local reference sets have now been AI-reviewed; see [scope](15-ai-source-review.md).
Development assessment reports remain local and explicitly identify AI-reviewed references.

The self-hosted backend engineering work is implemented. Human corpus review and final
benchmark acceptance remain open; this record does not certify extraction accuracy.

## Completed checks

- Windows, Python 3.13: 108 offline tests passed; five opt-in PostgreSQL tests skipped (or passed when PostgreSQL is configured).
- Linux, Python 3.13 in the built Docker image: 108 offline tests passed; the same five
  opt-in tests skipped. No provider credential or external corpus was mounted.
- Local PostgreSQL: all five isolated-schema integration tests passed, including crash
  recovery, owner fencing, shared capacity and concurrent idempotent submission.
- Dependency lock, lint (`ruff check`), formatting (`ruff format --check`), domain/port type checks and Compose configuration passed.
- A temporary Git index containing the complete proposed change passed publication checks,
  document metadata checks, fixture hash validation and the offline secret scanner. The real
  index was left unchanged. Ignored originals, drafts and model outputs were excluded.
- Docker image built successfully. Windows/Linux/macOS CI is configured, but no remote CI
  result or local macOS execution is claimed.

## Development model diagnostics and assessment

Budgeted development runs exercised native PDF, raster scans, mixed pages, DOCX and receipt
inputs, both routing and always-vision profiles, bounded candidate merging and per-page
parallel relevance calls. A real HTTP upload/submit/poll/result flow completed on a mixed-page fixture.

Relevance scoring defaults to `relevance_strategy="decisions"` using `perplexity/pplx-decider-v1.2`
with per-unit evaluation (`relevance_batch_units=1`) and high concurrency (`max_parallel_decision_batches=8`).
Full-document text is no longer concatenated into unit payloads (`document_context=""`), allowing each unit
to carry its own semantic text, neighbor excerpts, and visual content without quadratic token overhead.
In a 91-page document test (`gov-uk-pdf-disabled-facilities-grant-dfg-delivery-guidance-for-local-authorities-in-england-1`),
parallel scoring completed end-to-end in 102.9s for $0.0163, achieving 100% evidence recall and 83.3% accuracy
without memory pressure or token limit issues.

A complete 72-case development assessment across all 668 fields comparing `default` (`decision_led`)
and `always_vision` is compiled in `eval/results/ai-reviewed-development-assessment.json` and `.md`:
- **`default` (`decision_led`)**: 88.02% exact match accuracy (588/668), 97.90% field evidence match rate (654/668),
  **100.0% routing evidence recall** (zero false negatives), 39.57% selection fraction (filtering 60.4% of irrelevant pages),
  68.47% selected unit precision (vs 27.09% in always_vision), 0 failures, 77 false-supported verifications,
  and $0.6161 total estimated cost (~$0.0085/case) with p50 latency of 13.0s.
- **`always_vision`**: 86.83% exact match accuracy (580/668), 87.28% normalized accuracy (583/668), 97.60% field evidence
  match rate (652/668), 100.0% routing recall (by inspecting 100% of all units), 0 failures, and $0.1724 total cost
  with p50 latency of 5.0s.

These are development diagnostics against owner-authorized AI-reviewed references. Disagreements and
false-supported outcomes remain visible. They establish integration behavior and prove that decision-led routing
improves extraction accuracy over unfiltered inputs while strictly preserving 100% evidence recall. Raw reports remain in
ignored `eval/results/`.

## Corpus and remaining acceptance

All 120 source identities, hashes, files, group assignments and 72/24/24 split memberships
were preserved. All 120 cases now have local annotation drafts. Calibration/holdout model
work was separately authorized for annotation only; the service was not evaluated or tuned
on those cases.

Corpus integrity validation passes. Zero cases have been approved as evaluation-ready.
`validate_corpus --require-ready` intentionally fails until actual human field/evidence,
rights/privacy and group reviews are recorded. The local review queue is
`eval/cache/human-review/index.md`; preparing it preserves existing nonempty reviewer copies.
Drafts are ignored model output and require a local backup to survive a clean checkout.

Follow the [review and release procedure](13-operations-and-release.md), freeze the reviewed
corpus, then run the final budgeted benchmark before closing M0 and benchmark acceptance in M6.
