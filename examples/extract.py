"""Submit an extraction and poll its durable job. The service invokes paid models."""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--instructions", default="")
    parser.add_argument(
        "--profile",
        default="default",
        choices=["default", "always_vision", "text_only", "decision_no_verify"],
    )
    parser.add_argument("--max-wait-seconds", type=float, default=650)
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=650) as client:
        with args.document.open("rb") as source:
            response = client.post("/v1/documents", files={"file": (args.document.name, source)})
        response.raise_for_status()
        document_id = response.json()["document_id"]
        response = client.post(
            "/v1/extractions",
            json={
                "document_id": document_id,
                "schema": json.loads(args.schema.read_text("utf-8")),
                "instructions": args.instructions,
                "model_profile": args.profile,
            },
        )
        response.raise_for_status()
        job_id = response.json()["job_id"]
        print(f"Submitted {job_id}", file=sys.stderr)
        deadline = time.monotonic() + args.max_wait_seconds
        while time.monotonic() < deadline:
            response = client.get(f"/v1/extractions/{job_id}")
            response.raise_for_status()
            status = response.json()
            if status["status"] in ("failed", "cancelled"):
                raise SystemExit(f"Job {job_id}: {status['status']}; {status.get('last_error')}")
            if status["status"] in ("completed", "completed_with_unresolved"):
                response = client.get(f"/v1/extractions/{job_id}/result")
                response.raise_for_status()
                print(json.dumps(response.json(), indent=2, ensure_ascii=False))
                return
            time.sleep(1)
        raise SystemExit(
            f"Polling timed out; inspect the persisted job {job_id} before resubmitting."
        )


if __name__ == "__main__":
    main()
