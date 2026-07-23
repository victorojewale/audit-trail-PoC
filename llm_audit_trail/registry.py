"""Canonical event-type names and the JSON Schemas that describe them."""

from __future__ import annotations

import json
from typing import Any, Dict, List

__all__ = ["EventTypes", "SCHEMA_FILES", "load_schema", "available_schemas"]


class EventTypes:
    """Event labels emitted by this library.

    ``event_type`` is a free-form string — these are the ones the bundled
    helpers and schemas use.
    """

    # governance
    APPROVAL = "Approval"
    RISK_WAIVER = "RiskWaiver"
    ATTESTATION = "Attestation"

    # data provenance
    DATASET_REGISTERED = "DatasetRegistered"
    DATASET_ATTESTATION = "DatasetAttestation"

    # training lifecycle
    FINE_TUNE_START = "FineTuneStart"
    FINE_TUNE_END = "FineTuneEnd"
    EPOCH_END = "EpochEnd"
    EVALUATION = "Evaluation"
    CHECKPOINT = "Checkpoint"

    # serving
    INFERENCE_REQUEST = "InferenceRequest"
    INFERENCE_RESPONSE = "InferenceResponse"


SCHEMA_FILES: Dict[str, str] = {
    EventTypes.APPROVAL: "approval.schema.json",
    EventTypes.RISK_WAIVER: "riskwaiver.schema.json",
    EventTypes.ATTESTATION: "attestation.schema.json",
    EventTypes.DATASET_REGISTERED: "dataset_registered.schema.json",
}


def available_schemas() -> List[str]:
    """Event types that ship with a JSON Schema for their ``details``."""
    return sorted(SCHEMA_FILES)


def load_schema(event_type: str) -> Dict[str, Any]:
    """Load the bundled JSON Schema for an event type's ``details`` object.

    Raises:
        KeyError: if no schema ships for ``event_type``.
    """
    try:
        filename = SCHEMA_FILES[event_type]
    except KeyError:
        raise KeyError(
            f"no bundled schema for {event_type!r}; have {available_schemas()}"
        ) from None

    from importlib.resources import files

    resource = files(__package__).joinpath("schemas", filename)
    return json.loads(resource.read_text(encoding="utf-8"))
