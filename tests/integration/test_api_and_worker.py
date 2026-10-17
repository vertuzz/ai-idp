from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ai_idp.adapters.inbound.http.app import create_app
from ai_idp.adapters.inbound.http.dependencies import build_container
from ai_idp.application.ports.protocols import (
    ExtractionBatchResult,
    ModalityResult,
    RelevanceBatchResult,
    RelevanceResult,
    UnitInputPayload,
    VerificationBatchResult,
)
from ai_idp.domain.enums import DecisionKind, Modality, VerificationStatus
from ai_idp.domain.models import (
    DecisionRecord,
    Evidence,
    ExtractionSpecification,
    ModalityDecision,
    TargetFieldSpec,
    UsageRecord,
    VerificationOutcome,
)
from ai_idp.settings import Settings
from ai_idp.workers.runner import WorkerRunner

ROOT = Path(__file__).resolve().parents[2]


class FakeDecisionEngine:
    """Controllable DecisionEngine for deterministic integration testing."""

    def __init__(self, *, contradict_first_attempt_for: set[str] | None = None) -> None:
        self._contradict_set = contradict_first_attempt_for or set()
        self._verify_counts: dict[str, int] = {}

    async def score_relevance_batch(self, job_id, unit_payloads, fields, instructions, model_id):
        import uuid

        results = {}
        for payload in unit_payloads:
            result = await self.score_relevance(job_id, payload, fields, instructions, model_id)
            results[result.unit_id] = result
        usage = next(iter(results.values())).usage.model_copy(update={"usage_id": uuid.uuid4().hex})
        return RelevanceBatchResult(results=results, usage=usage)

    async def score_relevance(
        self,
        job_id: str,
        unit_payload: UnitInputPayload,
        fields: list[TargetFieldSpec],
        instructions: str,
        model_id: str,
        batch_questions: bool = True,
    ) -> RelevanceResult:
        uid = unit_payload.unit.unit_id
        is_first = unit_payload.unit.ordinal == 1
        prob = 0.92 if is_first else 0.12
        scores = {f.path: prob for f in fields}
        dists = {f.path: {"true": prob, "false": round(1.0 - prob, 4)} for f in fields}
        records = [
            DecisionRecord(
                decision_id=f"dec_rel_{job_id}_{uid}_{f.path}",
                job_id=job_id,
                unit_id=uid,
                field_path=f.path,
                kind=DecisionKind.RELEVANCE,
                model_id=model_id,
                scores=dists[f.path],
                selected=is_first,
                latency_ms=15,
            )
            for idx, f in enumerate(fields)
        ]
        usage = UsageRecord(
            usage_id=f"use_rel_{job_id}_{uid}",
            job_id=job_id,
            stage="scoring_relevance",
            model_id=model_id,
            tokens_in=150,
            tokens_out=0,
            estimated_cost_usd=0.000003,
            latency_ms=15,
        )
        return RelevanceResult(
            unit_id=uid,
            field_scores=scores,
            raw_distributions=dists,
            decision_records=records,
            usage=usage,
        )

    async def select_modality(
        self,
        job_id: str,
        unit_payload: UnitInputPayload,
        fields: list[TargetFieldSpec],
        model_id: str,
    ) -> ModalityResult:
        uid = unit_payload.unit.unit_id
        avail = unit_payload.unit.available_modalities
        chosen = Modality.TEXT if Modality.TEXT in avail else avail[0]
        probs = {"TEXT": 0.85, "VISION": 0.10, "TEXT_AND_VISION": 0.05}
        decision = ModalityDecision(
            unit_id=uid,
            modality=chosen,
            raw_probabilities=probs,
            available_modalities=avail,
        )
        record = DecisionRecord(
            decision_id=f"dec_mod_{job_id}_{uid}",
            job_id=job_id,
            unit_id=uid,
            kind=DecisionKind.MODALITY,
            model_id=model_id,
            scores=probs,
            selected=chosen.value,
            latency_ms=10,
        )
        usage = UsageRecord(
            usage_id=f"use_mod_{job_id}_{uid}",
            job_id=job_id,
            stage="selecting_modality",
            model_id=model_id,
            tokens_in=100,
            tokens_out=0,
            estimated_cost_usd=0.000002,
            latency_ms=10,
        )
        return ModalityResult(decision=decision, decision_record=record, usage=usage)

    async def verify_fields(
        self,
        job_id: str,
        fields_to_verify: list[tuple[TargetFieldSpec, Any, list[Evidence]]],
        unit_payloads_by_id: dict[str, UnitInputPayload],
        model_id: str,
    ) -> VerificationBatchResult:
        outcomes: dict[str, VerificationOutcome] = {}
        records: list[DecisionRecord] = []
        for idx, (f_spec, _val, _evs) in enumerate(fields_to_verify):
            count = self._verify_counts.get(f_spec.path, 0) + 1
            self._verify_counts[f_spec.path] = count
            if f_spec.path in self._contradict_set and count == 1:
                status = VerificationStatus.CONTRADICTED
                probs = {"SUPPORTED": 0.05, "CONTRADICTED": 0.90, "INSUFFICIENT_EVIDENCE": 0.05}
            else:
                status = VerificationStatus.SUPPORTED
                probs = {"SUPPORTED": 0.97, "CONTRADICTED": 0.01, "INSUFFICIENT_EVIDENCE": 0.02}
            outcomes[f_spec.path] = VerificationOutcome(
                field_path=f_spec.path,
                status=status,
                raw_probabilities=probs,
                model_id=model_id,
            )
            records.append(
                DecisionRecord(
                    decision_id=f"dec_ver_{job_id}_{f_spec.name}_{count}_{idx}",
                    job_id=job_id,
                    field_path=f_spec.path,
                    kind=DecisionKind.VERIFICATION,
                    model_id=model_id,
                    scores=probs,
                    selected=status.value,
                    latency_ms=12,
                )
            )
        usage = UsageRecord(
            usage_id=f"use_ver_{job_id}_{sum(self._verify_counts.values())}",
            job_id=job_id,
            stage="verifying",
            model_id=model_id,
            tokens_in=200,
            tokens_out=0,
            estimated_cost_usd=0.000004,
            latency_ms=12,
        )
        return VerificationBatchResult(outcomes=outcomes, decision_records=records, usage=usage)


class FakeExtractionEngine:
    """Controllable ExtractionEngine returning structured values and evidence."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[str]]] = []

    async def extract_fields(
        self,
        job_id: str,
        spec: ExtractionSpecification,
        target_fields: list[TargetFieldSpec],
        unit_inputs: list[tuple[UnitInputPayload, Modality]],
        model_id: str,
        stage_name: str = "extracting",
    ) -> ExtractionBatchResult:
        self.calls.append((stage_name, model_id, [f.path for f in target_fields]))
        first_uid = unit_inputs[0][0].unit.unit_id
        data: dict[str, Any] = {}
        evidences: dict[str, list[Evidence]] = {}
        for f in target_fields:
            if f.field_type in ("integer", "number"):
                data[f.name] = 1275 if stage_name == "escalating" else 1200
            else:
                data[f.name] = "TEST-NATIVE-01"
            evidences[f.path] = [Evidence(unit_id=first_uid, locator={}, quote=str(data[f.name]))]
        usage = UsageRecord(
            usage_id=f"use_ext_{job_id}_{len(self.calls)}",
            job_id=job_id,
            stage=stage_name,
            model_id=model_id,
            tokens_in=400,
            tokens_out=60,
            estimated_cost_usd=0.00007,
            latency_ms=85,
        )
        return ExtractionBatchResult(
            data=data,
            evidence_by_field=evidences,
            model_id=model_id,
            usage=usage,
        )


def test_http_api_worker_escalation_and_document_reuse(tmp_path: Path):
    db_file = tmp_path / "test.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{db_file.as_posix()}",
        local_storage_root=tmp_path / "storage",
        local_telemetry_root=tmp_path / "telemetry",
        relevance_top_k=1,
    )
    fake_dec = FakeDecisionEngine(contradict_first_attempt_for={"/net_total"})
    fake_ext = FakeExtractionEngine()
    container = build_container(
        settings,
        decision_engine=fake_dec,
        extraction_engine=fake_ext,
        create_tables=True,
    )
    app = create_app(container)
    client = TestClient(app)

    # 1. Health endpoints
    assert client.get("/health/live").status_code == 200
    ready_resp = client.get("/health/ready")
    assert ready_resp.status_code == 200
    assert ready_resp.json()["status"] == "ready"

    # 2. Upload multi-page PDF document
    pdf_path = ROOT / "eval" / "fixtures" / "synthetic" / "synthetic-mixed-01.pdf"
    with pdf_path.open("rb") as fh:
        up_resp = client.post(
            "/v1/documents",
            files={"file": ("synthetic-mixed-01.pdf", fh, "application/pdf")},
        )
    assert up_resp.status_code == 201
    doc_id = up_resp.json()["document_id"]
    assert up_resp.json()["status"] == "prepared"

    doc_meta = client.get(f"/v1/documents/{doc_id}")
    assert doc_meta.status_code == 200
    assert doc_meta.json()["units_count"] >= 2

    # 3. Submit Extraction #1 with Idempotency-Key
    schema_1 = {
        "type": "object",
        "properties": {
            "record_id": {"type": "string", "description": "Record identifier"},
            "net_total": {"type": "integer", "description": "Net total"},
        },
        "required": ["record_id", "net_total"],
    }
    ext_resp = client.post(
        "/v1/extractions",
        headers={"Idempotency-Key": "idem-key-001"},
        json={
            "document_id": doc_id,
            "schema": schema_1,
            "instructions": "Extract current period values.",
        },
    )
    assert ext_resp.status_code == 202
    job_id = ext_resp.json()["job_id"]

    # Repeated submission with same Idempotency-Key returns same job_id
    dup_resp = client.post(
        "/v1/extractions",
        headers={"Idempotency-Key": "idem-key-001"},
        json={
            "document_id": doc_id,
            "schema": schema_1,
            "instructions": "Extract current period values.",
        },
    )
    assert dup_resp.status_code == 202
    assert dup_resp.json()["job_id"] == job_id

    # 4. Run WorkerRunner to lease and execute the job
    import asyncio

    worker = WorkerRunner(container, worker_id="test_worker_1")
    processed_id = asyncio.run(worker.process_one_if_available())
    assert processed_id == job_id

    # 5. Inspect job status, result, and decisions
    status_resp = client.get(f"/v1/extractions/{job_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "completed"

    res_resp = client.get(f"/v1/extractions/{job_id}/result")
    assert res_resp.status_code == 200
    res_body = res_resp.json()
    assert res_body["schema_valid"] is True
    assert res_body["data"]["record_id"] == "TEST-NATIVE-01"
    # Verify that /net_total escalated to google/gemini-4-argon on attempt 2
    assert res_body["data"]["net_total"] == 1275
    assert res_body["fields"]["/net_total"]["attempt_count"] == 2
    assert res_body["fields"]["/net_total"]["verification"] == "SUPPORTED"
    assert any(
        call[0] == "escalating" and call[1] == "google/gemini-4-argon" for call in fake_ext.calls
    )

    dec_resp = client.get(f"/v1/extractions/{job_id}/decisions")
    assert dec_resp.status_code == 200
    assert len(dec_resp.json()["decisions"]) >= 4

    # 6. Reuse same document with a second schema without re-uploading
    schema_2 = {
        "type": "object",
        "properties": {"currency": {"type": "string"}},
        "required": ["currency"],
    }
    ext2_resp = client.post(
        "/v1/extractions?run_inline=true",
        json={"document_id": doc_id, "schema": schema_2},
    )
    assert ext2_resp.status_code == 202
    job2_id = ext2_resp.json()["job_id"]
    assert client.get(f"/v1/extractions/{job2_id}/result").status_code == 200
