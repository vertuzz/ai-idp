"""Transparent, mechanical work planning; this never predicts source relevance."""

from math import ceil

from ai_idp.application.services.partitioned_extraction import contains_array
from ai_idp.domain.models import PipelineConfiguration


def estimate_work(units, fields, config: PipelineConfiguration) -> dict:
    count = len(units)
    routed = config.pipeline_mode.value not in {"text_only", "always_vision"}
    routing = (
        ceil(
            count
            / min(
                config.relevance_batch_units,
                config.max_decision_questions_per_call,
                config.max_decision_images_per_call,
            )
        )
        if routed
        else 0
    )
    arrays = sum(contains_array(field.raw_schema) for field in fields)
    # This planning scenario assumes all units are relevant and one output page
    # per unit/collection. More records, byte limits and recovery increase it.
    planned = routing + (count if routed else 0) + count * arrays
    if config.pipeline_mode.value == "decision_led":
        planned += 2 * count * arrays
    planned += ceil(sum(not contains_array(f.raw_schema) for f in fields) / 8)
    warnings = []
    if arrays and count * arrays > config.max_extraction_parts:
        warnings.append(
            "Extracting a collection from every source unit would exceed the extraction-part limit."
        )
    if planned > config.max_model_calls:
        warnings.append(
            "The all-units planning scenario exceeds the model-call budget "
            "before value verification and recovery."
        )
    if any(unit.kind.value == "pdf_page" for unit in units):
        warnings.append(
            "PDF images are rendered on demand; page admission does not guarantee "
            "extraction fits the job budget."
        )
    return {
        "source_units": count,
        "minimum_routing_calls": routing,
        "all_units_calls_before_value_checks": planned,
        "model_call_limit": config.max_model_calls,
        "estimated_cost_limit_usd": config.max_job_estimated_cost_usd,
        "can_fit_minimum": routing <= config.max_model_calls,
        "assumptions": (
            "All units selected; one response page per source/collection. Value checks, "
            "extra output pages, byte splits, retries and recovery are additional. "
            "This is not a cost quote or accuracy estimate."
        ),
        "warnings": warnings,
    }
