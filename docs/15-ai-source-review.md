# Owner-authorized AI source review

On 2026-10-17 the owner explicitly delegated reference-answer checking to Codex and declined
manual review. This authorizes an AI-reviewed development assessment for MVP acceptance.
No human review or external validation is implied by that decision.

## Work performed

The 120 original identities, hashes and 72/24/24 split assignments were retained. Codex
read source-context records for every DocLayNet/government reference field, inspected rendered
pages and embedded logos for visual-only evidence, inspected all 30 original receipt images,
and checked synthetic values against original content, generator parameters and raster pages.
The five synthetic DOCX inspection labels have identical bytes; the shared PASS label was
inspected and each document's canonical block mapping was checked.

The resulting 1,024 expected fields include corrected values, explicit unknown nullable leaves
and source citations. Corrections include receipt item continuation/row associations, exact
number formatting, final payable amounts after rounding, contaminated quotations, ambiguous
task descriptions and previously unresolved synthetic DOCX source IDs. Ambiguous formula
notation and an artificial page-count question were removed from their respective tasks;
source cases were preserved. All corrected answer sets pass schema validation.

Original drafts, corrected answers, source excerpts, images and the detailed adjudication log
remain ignored local files. AI reviews record reviewer type, source checksum, timestamp and
notes. The manifest fingerprints the exact saved annotation bytes. AI review never sets the
human `evaluation_ready`, rights or split-group adjudication flags.

## Assessment boundary

Corrected development references were frozen before the new development service runs. The pipeline,
model prompts and selection thresholds were not tuned from protected annotations or outputs.
Calibration/holdout material was used for annotation checking only. AI-reviewed development
results are diagnostics; the runner keeps independent human benchmark requirements intact.

Local review index: `eval/cache/ai-review/index.md`. Results and the assessment summary live
under ignored `eval/results/`. Back up these files separately; source control does not contain
the model-generated or AI-reviewed answer bytes.

## Interpretation

An AI source review can still miss errors and can share failure modes with extraction models.
Receipt punctuation, formula transcription and ambiguous unpriced modifier lines can affect
strict match scores. The government portion includes many unfilled forms/templates; extracting
their static guidance does not establish accuracy on completed customer paperwork. Synthetic
files test controlled stresses rather than the full variety of real documents.
Synthetic templates also share substantial structure across splits. Treat them as controlled
stress cases rather than evidence of generalization to unseen document families; split
memberships were preserved and no protected service runs were performed.

Report observed failures and false-supported results alongside field accuracy, source/format
breakdowns, latency and cost. Do not describe this work as independent human ground truth,
probability calibration, redistribution clearance or a general production accuracy guarantee.
The owner's local MVP assessment can proceed without asking them to review every document.
