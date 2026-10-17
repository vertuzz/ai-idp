from __future__ import annotations

from ai_idp.application.ports.protocols import JobRepository, ResultRepository
from ai_idp.domain.enums import JobStatus
from ai_idp.domain.errors import (
    DocumentNotFoundError,
    JobNotCompletedError,
    JobNotFoundError,
)
from ai_idp.domain.models import (
    DecisionRecord,
    Document,
    DocumentUnit,
    ExtractionResult,
    ExtractionRun,
)


class InspectJobUseCase:
    """Retrieves documents, job status, finalized results, decisions, and handles cancellation."""

    def __init__(
        self,
        *,
        job_repo: JobRepository,
        result_repo: ResultRepository,
    ) -> None:
        self._job_repo = job_repo
        self._result_repo = result_repo

    def get_document(self, document_id: str) -> tuple[Document, list[DocumentUnit]]:
        doc = self._job_repo.get_document(document_id)
        if doc is None:
            raise DocumentNotFoundError(f"Document '{document_id}' not found.")
        units = self._job_repo.get_units(document_id)
        return doc, units

    def get_job(self, job_id: str) -> ExtractionRun:
        job = self._job_repo.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"Extraction job '{job_id}' not found.")
        return job

    def get_result(self, job_id: str) -> ExtractionResult:
        job = self.get_job(job_id)
        if job.status not in (
            JobStatus.COMPLETED,
            JobStatus.COMPLETED_WITH_UNRESOLVED,
        ):
            raise JobNotCompletedError(
                f"Extraction job '{job_id}' is in status '{job.status}', "
                "result is not yet available."
            )
        spec = self._job_repo.get_spec(job.spec_id)
        if spec is None:
            raise JobNotFoundError(f"Specification '{job.spec_id}' not found.")
        result = self._result_repo.get_extraction_result(job_id, spec)
        if result is None:
            raise JobNotCompletedError(f"Result for job '{job_id}' is not persisted.")
        return result

    def list_decisions(self, job_id: str) -> list[DecisionRecord]:
        self.get_job(job_id)
        return self._result_repo.list_decisions(job_id)

    def cancel_job(self, job_id: str) -> ExtractionRun:
        self.get_job(job_id)
        return self._job_repo.request_cancel(job_id)
