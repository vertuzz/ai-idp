# MVP engineering validation — 2026-10-17

Follow-up: the owner authorized AI source review after this engineering snapshot.
All 120 local reference sets have now been AI-reviewed; see [scope](15-ai-source-review.md).
Development assessment reports remain local and explicitly identify AI-reviewed references.

The self-hosted backend engineering work is implemented. Human corpus review and final
benchmark acceptance remain open; this record does not certify extraction accuracy.

## Completed checks

- Windows, Python 3.13: 90 offline tests passed; five opt-in PostgreSQL tests skipped.
- Linux, Python 3.13 in the built Docker image: 90 offline tests passed; the same five
  opt-in tests skipped. No provider credential or external corpus was mounted.
- Local PostgreSQL: all five isolated-schema integration tests passed, including crash
  recovery, owner fencing, shared capacity and concurrent idempotent submission.
- Dependency lock, lint, formatting, domain/port type checks and Compose configuration passed.
- A temporary Git index containing the complete proposed change passed publication checks,
  document metadata checks, fixture hash validation and the offline secret scanner. The real
  index was left unchanged. Ignored originals, drafts and model outputs were excluded.
- Docker image built successfully. Windows/Linux/macOS CI is configured, but no remote CI
  result or local macOS execution is claimed.

## Development model diagnostics

Budgeted development runs exercised native PDF, raster scans, mixed pages, DOCX and receipt
inputs, both routing and always-vision profiles, bounded candidate merging and single-question
relevance calls. A real HTTP upload/submit/poll/result flow completed on a mixed-page fixture.

A 27-page development PDF exposed a provider rejection when verification included twelve
images. Verification now counts all images and respects a configurable image capability
limit; the subsequent run completed. The failed runs remain in local diagnostic reports.
Unsupported DOCX vector images are retained with warnings and prevent verified global absence.

These are small development diagnostics against unreviewed references. Disagreements and
false-supported outcomes remain visible. They establish integration behavior, not a reliable
accuracy estimate, calibrated probabilities or a completed benchmark. Raw reports remain in
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
