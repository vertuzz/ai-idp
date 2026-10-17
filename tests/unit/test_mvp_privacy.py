import pytest

from ai_idp.adapters.outbound.telemetry.otel import OpenTelemetryJsonlAdapter
from ai_idp.application.services.request_budget import RequestBudget, active_request_budget
from ai_idp.domain.errors import BudgetExhaustedError


def test_exception_messages_and_causes_are_not_exported(tmp_path):
    telemetry = OpenTelemetryJsonlAdapter(tmp_path)
    with pytest.raises(RuntimeError):
        with telemetry.span("test.failure"):
            try:
                raise ValueError("PRIVATE_SOURCE_PAYLOAD")
            except ValueError as exc:
                raise RuntimeError("PRIVATE_PROVIDER_RESPONSE") from exc
    content = "".join(p.read_text("utf-8") for p in tmp_path.glob("*.jsonl"))
    assert "PRIVATE_SOURCE_PAYLOAD" not in content
    assert "PRIVATE_PROVIDER_RESPONSE" not in content
    assert "RuntimeError" in content


def test_physical_request_reservations_cannot_exceed_budget():
    budget = RequestBudget(2)
    token = active_request_budget.set(budget)
    try:
        budget.reserve()
        budget.reserve()
        with pytest.raises(BudgetExhaustedError):
            budget.reserve()
        assert budget.used == 2
    finally:
        active_request_budget.reset(token)
