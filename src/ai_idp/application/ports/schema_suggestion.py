from __future__ import annotations

from typing import Any, Protocol

from ai_idp.application.ports.protocols import UnitInputPayload
from ai_idp.domain.models import UsageRecord
from ai_idp.domain.schema_suggestion import SuggestionJob


class SchemaDecisionEngine(Protocol):
    async def assess_schema(
        self,
        job_id: str,
        payloads: list[UnitInputPayload],
        questions: dict[str, Any],
        model_id: str,
    ) -> tuple[dict[str, Any], UsageRecord]: ...


class SchemaGenerationEngine(Protocol):
    async def propose_schema(
        self,
        job_id: str,
        payloads: list[UnitInputPayload],
        model_id: str,
        repair: str = "",
    ) -> tuple[dict[str, Any], UsageRecord]: ...


class SuggestionRepository(Protocol):
    def create(self, job: SuggestionJob, key: str | None) -> SuggestionJob: ...
    def get(self, job_id: str) -> SuggestionJob | None: ...
    def claim(self, owner: str, lease_seconds: int) -> SuggestionJob | None: ...
    def heartbeat(self, job_id: str, owner: str, lease_seconds: int) -> bool: ...
    def save(self, job: SuggestionJob, owner: str) -> None: ...
    def reserve_request(self, job_id: str, owner: str, limit: int) -> None: ...
    def cancel(self, job_id: str) -> None: ...
