import asyncio
from functools import partial

import pymupdf
import pytest

from ai_idp.application.services.pipeline import _run_bounded
from ai_idp.application.services.request_budget import (
    RequestBudget,
    active_request_budget,
)
from ai_idp.domain.errors import BudgetExhaustedError, ProviderError
from tests.integration.test_api_and_worker import FakeDecisionEngine
from tests.integration.test_pipeline_recovery import make_available, setup


class TrackingDecisionEngine(FakeDecisionEngine):
    def __init__(self, *, physical_attempts=False):
        super().__init__()
        self.calls = []
        self.active = 0
        self.peak = 0
        self.physical_attempts = physical_attempts
        self.attempts = 0

    async def score_relevance_batch(self, **kwargs):
        budget = active_request_budget.get()
        if self.physical_attempts:
            budget.reserve()
            self.attempts += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            self.calls.append(
                (
                    [p.unit.unit_id for p in kwargs["unit_payloads"]],
                    [f.path for f in kwargs["fields"]],
                )
            )
            await asyncio.sleep(0.01)
            return await super().score_relevance_batch(**kwargs)
        finally:
            self.active -= 1


def multipage_job(c, *, fields=3):
    pdf = pymupdf.open()
    for number in range(9):
        pdf.new_page().insert_text((50, 50), f"Synthetic page {number + 1}")
    raw = pdf.tobytes()
    pdf.close()
    doc = c.ingest_use_case.execute(raw_bytes=raw, filename="routing-fixture.pdf")
    schema = {
        "type": "object",
        "properties": {f"value_{i}": {"type": "string"} for i in range(fields)},
    }
    return c.request_extraction_use_case.execute(document_id=doc.document_id, schema_json=schema)


async def test_page_and_field_batches_are_bounded_parallel_and_resume_without_repayment(tmp_path):
    from unittest.mock import patch

    decision = TrackingDecisionEngine()
    c, _, _ = setup(
        tmp_path,
        decision=decision,
        relevance_batch_units=2,
        max_decision_questions_per_call=3,
        max_parallel_decision_batches=2,
        max_field_extra_attempts=0,
        max_coverage_reviews=0,
    )
    job = multipage_job(c)
    with patch.object(c.result_repo, "save_final_result", side_effect=RuntimeError("crash")):
        with pytest.raises(RuntimeError, match="crash"):
            await c.pipeline_service.execute_job(job.job_id)
    assert decision.peak == 2
    assert decision.active == 0
    assert all(
        len(units) <= 2 and len(units) * len(fields) <= 3 for units, fields in decision.calls
    )
    pairs = [(uid, field) for units, fields in decision.calls for uid in units for field in fields]
    assert len(pairs) == len(set(pairs)) == 27
    selection = c.result_repo.load_step(job.job_id, "routing:selection")
    assert selection["selected_unit_ids"] == ["page_000001", "page_000002"]
    assert c.job_repo.get_job(job.job_id).progress.units_scored == 9
    paid_batches = len(decision.calls)
    make_available(c, job.job_id)
    await c.pipeline_service.execute_job(job.job_id)
    assert len(decision.calls) == paid_batches


async def test_concurrent_attempts_share_one_job_budget_and_cancel_siblings(tmp_path):
    decision = TrackingDecisionEngine(physical_attempts=True)
    c, _, _ = setup(
        tmp_path,
        decision=decision,
        max_model_calls=3,
        relevance_batch_units=1,
        max_parallel_decision_batches=2,
    )
    job = multipage_job(c, fields=1)
    with pytest.raises(BudgetExhaustedError):
        await c.pipeline_service.execute_job(job.job_id)
    assert decision.attempts == 3
    assert decision.active == 0
    assert c.job_repo.get_job(job.job_id).usage.llm_calls == 3


async def test_parallel_workers_preserve_order_and_drain_on_failure():
    gate = asyncio.Event()
    active = 0

    async def value(index):
        nonlocal active
        active += 1
        try:
            if index == 0:
                await gate.wait()
            else:
                gate.set()
            return index
        finally:
            active -= 1

    assert await _run_bounded([partial(value, i) for i in range(6)], 2) == list(range(6))
    assert active == 0

    async def fail():
        await asyncio.sleep(0)
        raise ProviderError("injected")

    gate.clear()
    with pytest.raises(ProviderError):
        await _run_bounded([partial(value, 0), fail], 2)
    assert active == 0


def test_retries_share_parent_request_and_spend_limits():
    parent = RequestBudget(3, cost_limit=0.05)
    first, second = RequestBudget(3, parent=parent), RequestBudget(3, parent=parent)
    first.reserve()
    second.reserve()
    first.reserve()
    with pytest.raises(BudgetExhaustedError):
        second.reserve()
    assert (parent.used, first.used, second.used) == (3, 2, 1)
    parent = RequestBudget(10, cost_limit=0.05)
    first, second = RequestBudget(10, parent=parent), RequestBudget(10, parent=parent)
    first.reserve()
    first.report_cost(0.06)
    with pytest.raises(BudgetExhaustedError):
        second.reserve()
    assert parent.used == 1
