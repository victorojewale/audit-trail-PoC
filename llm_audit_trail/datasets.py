"""Dataset provenance events."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .core import AuditLogger
from .registry import EventTypes

__all__ = ["register_dataset", "dataset_attestation"]


def register_dataset(
    log: AuditLogger,
    *,
    dataset_id: str,
    version: str,
    source: str,
    rows: int,
    license: Optional[str] = None,
    datasheet_url: Optional[str] = None,
    content_hash: str,
    preprocessing: Optional[Dict[str, Any]] = None,
    pii_residual_risk: Optional[str] = None,
    owner: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a dataset so later training and evaluation events can cite it."""
    return log.emit(
        EventTypes.DATASET_REGISTERED,
        details={
            "version": version,
            "source": source,
            "rows": rows,
            "license": license,
            "datasheet_url": datasheet_url,
            "content_hash": content_hash,
            "preprocessing": preprocessing or {},
            "pii_residual_risk": pii_residual_risk,
            "owner": owner,
        },
        dataset_id=dataset_id,
        system="data_engineering",
        actor=owner,
    )


def dataset_attestation(
    log: AuditLogger,
    *,
    dataset_id: str,
    statement: str,
    owner: str,
    references: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Record a human statement about a dataset (provenance, consent, PII)."""
    return log.emit(
        EventTypes.DATASET_ATTESTATION,
        details={
            "statement": statement,
            "owner": owner,
            "references": references or [],
        },
        dataset_id=dataset_id,
        system="governance",
        actor=owner,
    )
