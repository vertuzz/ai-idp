"""Opt-in real database locking and migration regression; no provider calls."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from ai_idp.adapters.inbound.http.dependencies import build_container
from ai_idp.settings import Settings
from tests.integration.test_postgres_leases import postgres_url  # noqa: F401
from tests.integration.test_schema_suggestions import seed_document


def test_postgres_suggestion_claims_share_capacity_and_fence_owners(tmp_path, postgres_url):  # noqa: F811
    core = build_container(
        Settings(
            _env_file=None,
            database_url=postgres_url,
            local_storage_root=tmp_path / "files",
            local_telemetry_root=tmp_path / "traces",
            max_concurrent_jobs=1,
            api_key="",
        )
    )
    seed_document(core, "doc_one")
    repo = core.suggestion_service.repo
    core.suggestion_service.submit(["doc_one"])
    core.suggestion_service.submit(["doc_one"])
    barrier = Barrier(2)

    def claim(owner):
        barrier.wait()
        return owner, repo.claim(owner, 120)

    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(claim, ["one", "two"]))
    assert sum(job is not None for _, job in claims) == 1
    owner, job = next((owner, job) for owner, job in claims if job is not None)
    assert not repo.heartbeat(job.job_id, "other-owner", 120)
    assert repo.heartbeat(job.job_id, owner, 120)
    repo.cancel(job.job_id)
    assert repo.claim("next-owner", 120)
