# Local development and stack ownership

## Choose one entry point

| Task | Start from | HTTP address | Long-running services |
|---|---|---|---|
| Work on the public engine/API | This repository | `http://127.0.0.1:8000/docs` | Core API, core worker, PostgreSQL |
| Work on the complete commercial product | Cloud sibling repository | `http://127.0.0.1:8010/` | Unified Cloud API/UI with embedded core, Cloud worker, PostgreSQL |

The public engine runs independently of commercial code. Cloud imports the editable
core package and runs its routes in the **same HTTP application**. Starting the full
product does not require an additional core API, core worker or frontend server.
Only run both stacks when intentionally comparing independent deployments.

## Prerequisites and first start

Install Python 3.13 through uv, Docker with Compose v2.20+ and start the Docker engine.
On Windows use Docker Desktop with Linux containers. The commands below also work
on Linux and macOS; no shell activation or PowerShell wrapper is required.

From this repository root:

```text
uv sync --locked --group dev --group evaluation
uv run --locked python scripts/dev.py up
```

The script creates an ignored `.env` from `.env.example` only when missing. Existing
configuration is preserved. Startup builds the locked image, waits for PostgreSQL,
runs Alembic migrations, and waits for API and worker database readiness. The worker
health probe checks schema readiness; it is not a job-throughput or provider probe.
Initial builds require internet access and may take several minutes.
The default startup readiness timeout is 300 seconds (`up --timeout 600` to extend).

Startup and health checks do not submit model work. Configure `OPENROUTER_API_KEY`
in `.env` before explicitly authorized, budgeted extraction. A worker can resume
previously queued jobs in its persistent database: stop it when finished with paid work.

## Daily commands

Use the same commands from either repository; each owns a different fixed Compose project.

```text
uv run --locked python scripts/dev.py status
uv run --locked python scripts/dev.py logs --tail 100
uv run --locked python scripts/dev.py logs --follow
uv run --locked python scripts/dev.py restart
uv run --locked python scripts/dev.py up
uv run --locked python scripts/dev.py down
```

`up` reuses the project and rebuilds/recreates services as needed. It does not allocate
a new port or project per invocation. Python sources are mounted read-only from the
checkout; use `restart` after source edits. Static Cloud assets are served directly.
Use `up` after changes to `.env`, dependencies, Dockerfiles or migrations; `restart`
alone does not apply changed environment variables or rebuild dependencies.
`logs` shows a bounded snapshot by default; only `--follow` waits continuously.

`down` stops/removes this project's containers and network, including PostgreSQL,
and preserves named volumes. It gives workers 35 seconds to finish active work;
unfinished jobs recover through their leases. It never deletes data volumes, kills
all Python/Node processes, or stops unrelated Docker projects. Native processes and
the older `docker-compose.yml` deployment are outside this command's ownership.

The core project is `ai-idp-core-dev`, with named volumes
`ai-idp-core-dev_postgres` and `ai-idp-core-dev_runtime`. PostgreSQL has **no host
port**. API and worker share storage under `/runtime/storage` and telemetry under
`/runtime/telemetry`. Dev Compose intentionally overrides host database/storage
settings to use this isolated database and these volumes. Host `data/`, SQLite
files, evaluation files and the existing `docker-compose.yml` volumes are untouched.
Never remove volumes as a routine restart or troubleshooting step.

## Troubleshooting and ownership

Run `status` before starting or troubleshooting. `migrate` exiting with code zero is
normal. A failed `up` returns nonzero and can leave diagnostic containers running;
inspect `logs`, fix the error, then rerun `up` or stop with `down`.
An occupied port fails instead of selecting a different port. Identify its owning
process/project and stop that specific development instance. Do not kill processes
just because their names contain Python, Node, uv or Docker.

`uv run --locked python scripts/dev.py check` validates Compose configuration quietly,
without printing interpolated secrets. Do not paste unredacted `docker compose config`,
environment dumps, database URLs or runtime logs into public issues.

If the older core deployment is running, inspect it with `docker compose ps` and
stop it with `docker compose stop`. Do not add `--volumes`. Native API/worker sessions
should be stopped with Ctrl+C in their original terminals. Remove temporary QA
servers after each check; do not turn ignored evaluation/data scripts into launchers.

## Native debugging alternative

Use native processes only when a debugger specifically needs them, with Compose
dev stopped. Copy `.env.example` to `.env` if needed and configure a host-accessible
database. The existing deployment Compose file can provide just PostgreSQL:

```text
docker compose up -d postgres
uv run --locked python -m alembic upgrade head
uv run --locked python -m uvicorn ai_idp.adapters.inbound.http.app:create_app --factory --host 127.0.0.1 --port 8000
```

In a second terminal from the same root and environment:

```text
uv run --locked python -m ai_idp.workers.runner
```

Stop both terminals with Ctrl+C, then `docker compose stop postgres`. Do not combine
native workers with a Cloud database: Cloud needs its billing-aware worker.

## Evaluation and CI

M0 corpus integrity remains the first evaluation check:

```text
uv run --locked --group evaluation python -m scripts.validate_corpus
uv run --locked --group dev --group evaluation python -m pytest -q
```

The CI `dev-stack` job uses this same `up` command on Linux, probes HTTP readiness
without provider credentials, collects logs on failure and runs `down` with `always()`.
Portable offline tests run on Windows, Linux and macOS. CI does not restore external
corpus originals, evaluate protected splits or run live models. The public workflow
does not check out or depend on the commercial repository.

The existing `docker-compose.yml` remains the standalone self-hosted deployment
configuration; it is distinct from this source-mounted dev stack. See
[operations](13-operations-and-release.md) for backups and production release gates.
