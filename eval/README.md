# Evaluation directory

The initial **planned** corpus comprises 120 documents; no source binaries or completed annotations have been committed yet.

- [Corpus design, licence review and annotation procedure](../docs/12-evaluation-corpus.md)
- [Evaluation metrics and execution strategy](../docs/09-evaluation-strategy.md)
- [Machine-readable target quotas](corpus-plan.yaml)

## Intended artifacts

- corpus-plan.yaml — committed target source quotas, splits, seed and dataset policy.
- manifest.jsonl — **future** frozen case inventory: source ID, original URL or upstream ID, revision, hash, format, licence, allowed usage, split, group ID, status, annotation paths. Only commit reviewed metadata.
- annotations/ — **future** human-reviewed ground-truth JSON (values, JSON Pointers, source-unit evidence), with licence/PII checks.
- downloads/ — local raw third-party files, **untracked**. Do not commit without explicit redistribution clearance.
- results/ — generated model experiments, **untracked** by default.
- fixtures/ — future small public redistributable synthetic examples and their attribution.

Implementation will provide a deterministic downloader/preparer and corpus validator. No fabricated corpus entries should be added merely to satisfy quota totals.

## Required preparation order

1. Review rights for each chosen source file and choose 20–30 real preview cases.
2. Obtain assets locally; record source IDs, revisions, SHA-256 and attribution.
3. Select and freeze exactly 120 cases (35 + 30 + 20 + 15 + 20) in the manifest, respecting grouped 72/24/24 splits.
4. Annotate schemas, values and evidence locations and review them.
5. Validate corpus, then run provider smoke tests and architecture experiments.

The project code is Apache 2.0, but downloaded corpus assets retain their original licences. Do not assume code licensing covers images, documents or model-generated output.
