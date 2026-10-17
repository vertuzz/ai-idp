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
