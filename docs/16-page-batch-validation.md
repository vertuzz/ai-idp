# Page-batch relevance validation — 2026-10-18

Pipeline v4 replaces unit/field relevance questions with one relevance question per
source unit against the complete requested field set. Each request contains up to
eight units and eight images, plus the units' text, all field descriptions/schemas
and caller guidance. Up to eight groups run concurrently. Optional fields remain
search targets. Threshold selection uses a document-wide top-two safety floor;
field evidence, verification and bounded recovery remain downstream stages.

## Engineering checks

- Corpus integrity validation passed for all 120 original identities and hashes.
- Python 3.13 on Windows: 109 offline tests passed; five opt-in PostgreSQL tests
  were skipped. The new live run used an isolated SQLite database, not PostgreSQL.
- Regression coverage includes 100 PDF pages and 80 fields (40 required): exactly
  13 relevance calls, all 80 fields in every call, 100 independent unit decisions,
  bounded parallelism, source order, shared budgets and replay without repeated calls.
- Adapter tests cover complete field descriptions, all images/text, missing/invalid
  answers, generative uncertainty retention and the absence of fabricated per-field
  scores. Pending v3 jobs fail before incompatible checkpoints or model calls are used.
- Lint, formatting, domain/port type checks and dependency-lock validation passed.
- Worktree publication checks inspected document metadata and fixture hashes;
  the offline secret scan found no findings in the changed publication files.

Live provider boundary probes accepted eight images with 80 field descriptions,
both with and without native text. Nine, ten, twenty and fifty images were rejected
with `At most 8 images are allowed per question`. These small synthetic probes
establish the current serving limit, not document-understanding accuracy.

## Existing development files

Run `eval_e9ae8f32feaf` exercised the full default pipeline on all **72 development
cases and 668 reference fields**, using the existing local AI-reviewed annotations.
The 24 calibration and 24 holdout cases were neither executed nor tuned on. Source
identities, splits, reference answers and thresholds were not changed for this run.
The explicit suite budget was $1.50; reported model expenditure was **$0.630840**.

| Measurement | Observed result |
|---|---:|
| Technical failures | 0 / 72 |
| Cases with unresolved fields | 2 / 72 |
| Schema-valid results | 72 / 72 |
| Exact and normalized reference matches | 596 / 668 (89.22%) |
| Field source-location matches | 658 / 668 (98.50%) |
| Expected evidence units retained by routing | 152 / 152 (100%) |
| Source units selected for extraction | 200 / 561 (35.65%) |
| Relevance requests | 123 |
| All pipeline requests | 576 |
| Incorrectly SUPPORTED values relative to the references | 69 |
| End-to-end median latency, including preparation | 10.98 s |
| End-to-end p95 latency, including preparation | 51.22 s |

| Source | Files | Reference matches | Routing evidence recall |
|---|---:|---:|---:|
| CORD receipt images | 18 | 276 / 304 (90.79%) | 100% |
| DocLayNet PDFs | 21 | 116 / 134 (86.57%) | 100% |
| Government DOCX | 9 | 54 / 62 (87.10%) | 100% |
| Government PDFs | 12 | 63 / 81 (77.78%) | 100% |
| Synthetic stress documents | 12 | 87 / 87 (100%) | 100% |

The 91-page PDF required **12 relevance requests** and selected 12 pages, preserving
all six reference evidence pages. Its final result matched five of six fields.
Downstream verification triggered full-source escalation for two initially correct
fields; those values remained correct, without improving the overall match count.
The complete job took 190.56 s including preparation and cost $0.346774, about 55%
of this suite's model expenditure. Reduced routing calls do not guarantee lower
total cost while verification and escalation remain expensive.

The historical composite v3 development report recorded 588/668 exact matches,
828 total requests, $0.616053 and a 12.99 s median. This v4 run recorded eight more
matches and 252 fewer requests, but slightly higher total expenditure. This is a
descriptive comparison of model runs, not a controlled repeated estimate or proof
that routing alone caused the accuracy difference.

## Interpretation and artifacts

The observed routing recall supports the new batching behavior on these files.
It does not establish correctness on unseen documents. The 69 false-supported
values are reference mismatches accepted by the verifier, not errors it caught.
`verified` remains a model verdict, and schema validity is a separate property.
AI-reviewed reference limitations and independent human benchmark gates remain as
described in [the source-review scope](15-ai-source-review.md).

Detailed JSON/CSV/Markdown reports remain ignored under
`eval/results/eval_e9ae8f32feaf.*`; per-stage request counts are in
`eval/results/eval_e9ae8f32feaf-routing.json`. Source artifacts, runtime databases,
probe outputs and the secret-scan report remain ignored under `eval/cache/`.
Only this aggregate engineering record is intended for source control.

Pending v3 jobs must be submitted again under v4; completed results remain readable.
See [the updated decision contract](04-decision-pipeline.md) for configuration and
recovery semantics.
