"""Opt-in live smoke check for configured OpenRouter decision, extraction, and escalation models."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BASE_URL = "https://openrouter.ai/api"
DEFAULT_DECISION_MODEL = "perplexity/pplx-decider-v1.2"
DEFAULT_EXTRACTION_MODEL = "anthropic/claude-haiku-5.5"
DEFAULT_ESCALATION_MODEL = "google/gemini-4-argon"

INVOICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "invoice_number": {"type": "string"},
        "total_amount": {"type": "number"},
    },
    "required": ["invoice_number", "total_amount"],
    "additionalProperties": False,
}


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    for key in (
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "AI_IDP_DECISION_MODEL",
        "AI_IDP_EXTRACTION_MODEL",
        "AI_IDP_ESCALATION_MODEL",
    ):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def resolve_settings(env: dict[str, str]) -> dict[str, str]:
    return {
        "api_key": env.get("OPENROUTER_API_KEY", ""),
        "base_url": env.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "decision_model": env.get("AI_IDP_DECISION_MODEL", DEFAULT_DECISION_MODEL),
        "extraction_model": env.get("AI_IDP_EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL),
        "escalation_model": env.get("AI_IDP_ESCALATION_MODEL", DEFAULT_ESCALATION_MODEL),
    }


def make_test_image_data_url() -> str:
    image = Image.new("RGB", (400, 120), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.text((20, 20), "INVOICE #INV-2026-042", fill=(0, 0, 0))
    draw.text((20, 60), "TOTAL AMOUNT: $1,250.00", fill=(0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_extraction_payload(model: str, data_url: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Extract the invoice number and total amount from this image.",
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "invoice_extraction",
                "strict": True,
                "schema": INVOICE_SCHEMA,
            },
        },
        "temperature": 0,
        "max_tokens": 200,
    }


def build_decision_payload(model: str, data_url: str) -> dict[str, Any]:
    return {
        "model": model,
        "state": [
            "Document page text: INVOICE #INV-2026-042. TOTAL AMOUNT: $1,250.00",
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
        "questions": {
            "has_total_amount": {
                "type": "noul",
                "instructions": "Does this unit directly provide the invoice total amount?",
                "criteria": {
                    "false": "The unit does not mention or clarify the invoice total amount.",
                    "true": "The unit directly states or clarifies the invoice total amount.",
                },
            },
            "modality": {
                "type": "choice",
                "instructions": "Which modality is needed to extract the fields?",
                "criteria": {
                    "TEXT": "Native text is sufficient.",
                    "VISION": "Image is required.",
                    "TEXT_AND_VISION": "Both text and image are helpful.",
                },
            },
            "verification": {
                "type": "choice",
                "instructions": "Does the source evidence support total_amount = 1250.0?",
                "criteria": {
                    "SUPPORTED": "Evidence directly supports the extracted value.",
                    "CONTRADICTED": "Evidence conflicts with the extracted value.",
                    "INSUFFICIENT_EVIDENCE": "Evidence is missing or ambiguous.",
                },
            },
        },
    }


def post_json(url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "ai-idp-smoke-models",
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} from {url}: {body}") from error


def run_smoke_check(settings: dict[str, str]) -> dict[str, Any]:
    if not settings["api_key"]:
        raise ValueError("OPENROUTER_API_KEY is required for live model smoke checks")

    data_url = make_test_image_data_url()
    base_url = settings["base_url"]

    decision_resp = post_json(
        f"{base_url}/alpha/decisions",
        settings["api_key"],
        build_decision_payload(settings["decision_model"], data_url),
    )
    answers = decision_resp.get("answers", {})
    expected_questions = {"has_total_amount", "modality", "verification"}
    if not expected_questions.issubset(answers):
        raise ValueError(f"Unexpected decision response shape: {decision_resp}")

    extraction_results: dict[str, Any] = {}
    for role, model in (
        ("extraction", settings["extraction_model"]),
        ("escalation", settings["escalation_model"]),
    ):
        resp = post_json(
            f"{base_url}/v1/chat/completions",
            settings["api_key"],
            build_extraction_payload(model, data_url),
        )
        content = resp["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        valid_invoice = parsed.get("invoice_number") == "INV-2026-042"
        valid_amount = float(parsed.get("total_amount", 0)) == 1250.0
        if not (valid_invoice and valid_amount):
            raise ValueError(f"Unexpected extracted payload from {model}: {parsed}")
        extraction_results[role] = {
            "requested_model": model,
            "returned_model": resp.get("model"),
            "extracted": parsed,
            "usage": resp.get("usage", {}),
        }

    return {
        "decision": {
            "requested_model": settings["decision_model"],
            "returned_model": decision_resp.get("model"),
            "answers": answers,
            "usage": decision_resp.get("usage", {}),
        },
        **extraction_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT / ".env",
        help="Path to .env file (default: repository .env)",
    )
    args = parser.parse_args()
    settings = resolve_settings(load_env(args.env_file))
    summary = run_smoke_check(settings)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
