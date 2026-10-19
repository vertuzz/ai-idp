# Project rules

- Read `README.md` and relevant `docs/` before changes; start with evaluation (M0).
- Evaluation entry points: `eval/README.md` (workflow), `eval/CORPUS.md` (catalog), `eval/manifest.jsonl` (120 candidate identities, hashes, splits and status). Files are complete; reviewed ground truth is not.
- Restore with `uv run --group evaluation python -m scripts.prepare_corpus`; validate with `uv run --group evaluation python -m scripts.validate_corpus`. Do not silently replace cases or tune on calibration/holdout.
- Use Python 3.13 and uv; run Python tools with `uv run` and commit `uv.lock`.
- Development currently runs on Windows; keep the project cross-platform (Windows, Linux, macOS). Use `pathlib`, portable commands, and no OS-specific runtime assumptions.
- Keep repository content in English and preserve domain/application/adapter boundaries.
- Let models decide content relevance and modality; retain field evidence and bounded recovery.
- Keep secrets, downloaded documents, and model outputs out of git. Track source licences and hashes; never call unreviewed labels ground truth.
- External originals and draft labels live in ignored `eval/downloads/`; cache/render tools in `eval/cache/`. Only project-owned fixtures in `eval/fixtures/synthetic/` are committed. Future reviewed schemas/answers/evidence belong in `eval/annotations/` with updated manifest references.
- Before publishing, inspect the staged files, document metadata, and secret/personal-data scan results; exclude local paths, credentials, external binaries, drafts, caches and model outputs.
- Test behavior changes; live model calls must be opt-in and budgeted.

## Development stack ownership

- Read `docs/22-local-development.md`. From this root use `uv run --locked python scripts/dev.py status` before starting, then `up` for the standalone core API/worker/PostgreSQL stack. The public repository must remain runnable without commercial code.
- For the complete commercial product use the sibling Cloud repository's `scripts/dev.py up` instead. Cloud embeds core and serves its own frontend; do not also launch a core API, core worker or frontend server for that stack. Never run a plain core worker against Cloud queues.
- Use the helper's `logs`, `restart`, `check` and `down` commands. Source edits need `restart`; configuration/dependency/migration changes need `up`. Fixed project names and ports prevent accidental duplicate instances. Do not invent fallback ports or launch ignored QA scripts as persistent services.
- The helper owns only `ai-idp-core-dev`; `down` preserves volumes. Never kill all Python/Node processes, remove volumes, or stop unrelated projects. Stop temporary processes/stacks you started when finished unless asked to leave them running; report any pre-existing stack you leave running. Native debugging is an explicit documented alternative and both API/worker terminals must be stopped afterward.
- Readiness and CI smoke checks make no provider calls or job submissions. Persistent workers can resume queued paid work. Keep runtime data, secrets and interpolated Compose configuration out of git and public logs.
