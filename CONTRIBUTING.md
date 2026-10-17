# Contributing

AI-IDP is a public, Apache-2.0-licensed general-purpose IDP experiment. Contributions are welcome when they keep the system explainable, replaceable, testable and independent of a specific business domain.

## Guidelines

- Use English for code, tests, comments, documentation, issue descriptions, pull requests, commit messages and user-visible API strings.
- Do not submit real confidential documents, personal data, credentials, private endpoints, copied proprietary datasets or confidential model outputs.
- Use synthetic, public-domain or explicitly redistribution-licensed test fixtures with attribution where necessary.
- Preserve hexagonal boundaries: domain/application code must not depend on provider SDKs, HTTP framework objects or storage implementation details.
- Include unit tests for behavior changes. For model-facing changes, include documented opt-in integration/evaluation instructions and expected cost.
- Preserve field-level evidence and avoid any UI/API claim that uncalibrated decision scores are correctness probabilities.
- Before proposing a new mandatory infrastructure dependency, explain why the PostgreSQL/local-only MVP is insufficient.
- Check dependency license compatibility with Apache 2.0 and record third-party notices if required.
- Follow the implementation milestones and document architecture changes in docs/11-decisions-and-open-questions.md.

## Local development

Use Python 3.13 through uv:

~~~text
uv sync --locked --group dev --group evaluation
uv run --locked pre-commit install
uv run --locked pre-commit run --all-files
~~~

Installing the hook is a one-time step for each checkout. Commits run Ruff lint and format
checks, offline lockfile validation, an offline secrets scan, Git-index publication checks,
and the basic unit suite under `tests/unit`. Checks report failures without changing files.
The publication check parses JSON/TOML/YAML, validates committed synthetic fixture hashes
and split groups, and rejects local artifacts, personal filesystem paths and unreviewed
document author metadata. It inspects staged bytes, including PDF/DOCX metadata.
These checks need no PostgreSQL, downloaded corpus, network secret verification or model calls.
Run `uv run --locked --group dev --group evaluation python -m pytest -q` for the full offline suite.

Run `uv run --locked ruff check .` and `uv run --locked ruff format --check .` directly when useful.
Use `uv run --group evaluation python -m scripts.prepare_corpus` to restore the 120-file
candidate corpus. Run `uv run --group evaluation python -m scripts.validate_corpus`
and `uv run --group evaluation python -m pytest -q` for corpus checks (see `eval/README.md`).

Development currently runs on Windows, but all project code and development entry points
must remain portable across Windows, Linux and macOS. Use `pathlib`, avoid shell-specific
setup/activation, and declare any unavoidable platform dependency explicitly. The current
bootstrap has been exercised on Windows only; other platforms still require verification.
`.gitattributes` keeps source text at LF and preserves binary fixture bytes/checksums across
platforms. Do not apply text line-ending normalization to document or image fixtures.

See README for Docker Compose, API, worker and PostgreSQL setup. Never commit a populated
.env file; use the example environment file instead.

## Security vulnerabilities

Follow [SECURITY.md](SECURITY.md); please do not publish exploitable vulnerability details in a public issue before a fix is available.
