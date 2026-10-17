# 06 — HTTP API Contracts (Draft)

Versioned REST API under /v1. All response shapes shown are *illustrative design contracts*, not implemented endpoints.

## POST /v1/documents

Multipart request: file. Optional metadata may be carried in a separate JSON form field. Accept only configured file types and limits.

Response 201:

~~~json
{
  "document_id": "doc_01",
  "filename": "sample.pdf",
  "media_type": "application/pdf",
  "sha256": "hex-digest",
  "status": "stored"
}
~~~

Use a server-generated storage key; the filename is display metadata only.

## POST /v1/extractions

~~~json
{
  "document_id": "doc_01",
  "schema": {
    "type": "object",
    "properties": {
      "invoice_total": {
        "type": ["number", "null"],
        "description": "Total amount due including tax"
      },
      "currency": {
        "type": ["string", "null"],
        "description": "ISO 4217 currency code"
      }
    },
    "required": ["invoice_total", "currency"]
  },
  "instructions": "Extract values from the document as written.",
  "model_profile": "default"
}
~~~

Response 202:

~~~json
{
  "job_id": "job_01",
  "document_id": "doc_01",
  "status": "pending",
  "links": {
    "self": "/v1/extractions/job_01",
    "result": "/v1/extractions/job_01/result"
  }
}
~~~

Optionally allow an Idempotency-Key header and return the original job ID for repeated equivalent submissions.

## GET /v1/extractions/{job_id}

~~~json
{
  "job_id": "job_01",
  "status": "running",
  "stage": "verifying",
  "progress": {
    "units_total": 80,
    "units_scored": 80,
    "fields_completed": 1,
    "fields_total": 2
  },
  "usage": {
    "llm_calls": 14,
    "estimated_cost_usd": 0.032
  },
  "created_at": "2026-10-17T10:00:00Z",
  "updated_at": "2026-10-17T10:00:42Z"
}
~~~

Status values: pending, running, completed, completed_with_unresolved, failed, cancelled. Progress counters are monotonic where feasible; field counts may increase as nested structures are discovered.

## GET /v1/extractions/{job_id}/result

~~~json
{
  "job_id": "job_01",
  "status": "completed",
  "data": {
    "invoice_total": 123.45,
    "currency": "EUR"
  },
  "schema_valid": true,
  "fields": {
    "/invoice_total": {
      "status": "verified",
      "verification": "SUPPORTED",
      "raw_probabilities": {
        "SUPPORTED": 0.97,
        "CONTRADICTED": 0.01,
        "INSUFFICIENT_EVIDENCE": 0.02
      },
      "sources": [
        {
          "unit_id": "unit_2",
          "locator": {"page_number": 2},
          "quote": "Total due EUR 123.45"
        }
      ],
      "attempt_count": 1
    }
  },
  "unresolved_fields": [],
  "usage": {
    "llm_calls": 18,
    "estimated_cost_usd": 0.041
  }
}
~~~

Scores above are fabricated examples for API illustration, not actual model measurements.

## Additional endpoints (later MVP)

- GET /v1/documents/{document_id} — metadata and preparation status.
- GET /v1/extractions/{job_id}/decisions — paginated debug decisions; restrict raw source access.
- POST /v1/extractions/{job_id}/cancel — request cancellation.
- GET /health/live and /health/ready.

## Errors and constraints

Use standard HTTP status codes with structured error ID, machine-readable code, and human-readable message. Examples: unsupported_media_type, upload_too_large, invalid_schema, document_not_found, rate_limited, job_budget_exhausted.

Do not echo secret values or raw document content in error messages. Keep a versioned schema support statement (for example, explicit policy for $ref, unions, nested arrays) and validate schema complexity before starting expensive work.

## Asynchrony and future hosting

The upload and extraction APIs are intentionally separate. Later a presigned S3 upload can replace multipart ingestion while keeping extraction requests unchanged. Authentication, tenant isolation, retention policies, webhooks, and billing are future SaaS capabilities, not implicit MVP functionality.
