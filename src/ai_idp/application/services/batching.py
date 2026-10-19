"""Mechanical request bounds; models retain responsibility for content choices."""

from __future__ import annotations

from ai_idp.application.ports.protocols import UnitInputPayload
from ai_idp.domain.enums import Modality
from ai_idp.domain.errors import ModelInputLimitExceededError


def input_size(payload: UnitInputPayload, modality: Modality) -> int:
    size = 1024
    if modality in (Modality.TEXT, Modality.TEXT_AND_VISION):
        size += len((payload.native_text or "").encode("utf-8"))
    if modality in (Modality.VISION, Modality.TEXT_AND_VISION):
        size += payload.image_size * 4 // 3 + 128 * payload.image_count
    return size


def unit_batches(
    inputs: list[tuple[UnitInputPayload, Modality]],
    *,
    max_units: int,
    max_bytes: int,
    max_images: int | None = None,
) -> list[list[tuple[UnitInputPayload, Modality]]]:
    batches: list[list[tuple[UnitInputPayload, Modality]]] = []
    batch: list[tuple[UnitInputPayload, Modality]] = []
    size = 0
    images = 0
    for item in inputs:
        item_bytes = input_size(*item)
        payload, modality = item
        item_images = (
            payload.image_count if modality in (Modality.VISION, Modality.TEXT_AND_VISION) else 0
        )
        if max_images is not None and item_images > max_images:
            raise ModelInputLimitExceededError("A source unit exceeds the model image limit.")
        if item_bytes > max_bytes:
            raise ModelInputLimitExceededError("A source unit exceeds the model input byte limit.")
        if batch and (
            len(batch) >= max_units
            or size + item_bytes > max_bytes
            or (max_images is not None and images + item_images > max_images)
        ):
            batches.append(batch)
            batch, size = [], 0
            images = 0
        batch.append(item)
        size += item_bytes
        images += item_images
    if batch:
        batches.append(batch)
    return batches
