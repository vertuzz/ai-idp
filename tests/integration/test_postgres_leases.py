"""Opt-in PostgreSQL regressions; never calls a model provider."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from ai_idp.adapters.outbound.persistence.models import JobQueueRow
from ai_idp.domain.enums import JobStatus
from ai_idp.domain.errors import JobLeaseLostError
from tests.integration.test_pipeline_recovery import (
    ControlledExtractor,
    make_available,
    setup,
)


@pytest.fixture
def postgres_url():
    base = os.environ.get("AI_IDP_TEST_POSTGRES_URL")
    if not base:
        pytest.skip("Set AI_IDP_TEST_POSTGRES_URL to run isolated PostgreSQL tests.")
    schema = "test_recovery_" + uuid.uuid4().hex
    engine = create_engine(base)
    with engine.begin() as db:
        db.execute(text(f"CREATE SCHEMA {schema}"))
    url = make_url(base).update_query_dict({"options": f"-csearch_path={schema}"})
    rendered = url.render_as_string(hide_password=False)
    try:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
        command.upgrade(config, "head")
        yield rendered
    finally:
        with engine.begin() as db:
            db.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        engine.dispose()


def test_postgres_allows_only_one_claim_and_fences_old_owner(tmp_path, postgres_url):
    c, _, job = setup(tmp_path, database_url=postgres_url)
    barrier = Barrier(2)

    def claim(owner):
        barrier.wait()
        return c.job_repo.claim_job(job.job_id, owner, 120)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, owner) for owner in ["first", "second"]]
        results = [f.result() for f in futures]
    assert sum(r is not None for r in results) == 1
    with c.job_repo._session_factory() as db:
        row = db.get(JobQueueRow, job.job_id)
        old_owner = row.lease_owner
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert c.job_repo.claim_job(job.job_id, "replacement", 120)
    with c.job_repo.execution_scope(job.job_id, old_owner):
        with pytest.raises(JobLeaseLostError):
            c.job_repo.complete_queue_item(job.job_id, JobStatus.COMPLETED)
        with pytest.raises(JobLeaseLostError):
            c.result_repo.save_final_result(job.job_id, JobStatus.COMPLETED, {})
    with c.job_repo._session_factory() as db:
        assert db.get(JobQueueRow, job.job_id).lease_owner == "replacement"


async def test_postgres_crash_resume_does_not_repeat_paid_inference(
    tmp_path, postgres_url, monkeypatch
):
    ext = ControlledExtractor(cost=0.06)
    c, _, job = setup(
        tmp_path, database_url=postgres_url, extractor=ext, max_job_estimated_cost_usd=0.10
    )
    save = c.result_repo.save_final_result

    def crash(*args, **kwargs):
        raise RuntimeError("Injected failure after inference")

    monkeypatch.setattr(c.result_repo, "save_final_result", crash)
    with pytest.raises(RuntimeError):
        await c.pipeline_service.execute_job(job.job_id)
    monkeypatch.setattr(c.result_repo, "save_final_result", save)
    make_available(c, job.job_id)
    result = await c.pipeline_service.execute_job(job.job_id)
    assert ext.calls == 1
    assert result.status == JobStatus.COMPLETED
    assert result.usage.estimated_cost_usd < 0.10
    assert result.fields["/record_id"].attempt_count == 1
