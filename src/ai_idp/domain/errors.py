from __future__ import annotations


class DomainError(Exception):
    """Base class for domain and application errors with machine-readable codes."""

    code: str = "domain_error"
    http_status: int = 400

    def __init__(
        self, message: str, *, code: str | None = None, http_status: int | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status


class UnsupportedMediaTypeError(DomainError):
    code = "unsupported_media_type"
    http_status = 415


class UploadTooLargeError(DomainError):
    code = "upload_too_large"
    http_status = 413


class DocumentLimitExceededError(DomainError):
    code = "document_limit_exceeded"
    http_status = 422


class MalformedDocumentError(DomainError):
    code = "malformed_document"
    http_status = 422


class InvalidSchemaError(DomainError):
    code = "invalid_schema"
    http_status = 422


class DocumentNotFoundError(DomainError):
    code = "document_not_found"
    http_status = 404


class JobNotFoundError(DomainError):
    code = "job_not_found"
    http_status = 404


class JobNotCompletedError(DomainError):
    code = "job_not_completed"
    http_status = 409


class BudgetExhaustedError(DomainError):
    code = "job_budget_exhausted"
    http_status = 429


class RateLimitedError(DomainError):
    code = "rate_limited"
    http_status = 429


class ProviderError(DomainError):
    code = "provider_error"
    http_status = 502


class JobLeaseLostError(DomainError):
    code = "job_lease_lost"
    http_status = 409
