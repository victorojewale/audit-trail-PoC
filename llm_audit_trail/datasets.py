
from __future__ import annotations
from typing import Optional, Dict, Any
from .core import AuditLogger

def register_dataset(
    log: AuditLogger,
    *,
    dataset_id: str,
    version: str,
    source: str,
    rows: int,
    license: Optional[str],
    datasheet_url: Optional[str],
    content_hash: str,
    preprocessing: Dict[str, Any],
    pii_residual_risk: Optional[str] = None,
    owner: Optional[str] = None,
):
    return log.emit(
        "DatasetRegistered",
        details={
            "version": version,
            "source": source,
            "rows": rows,
            "license": license,
            "datasheet_url": datasheet_url,
            "content_hash": content_hash,
            "preprocessing": preprocessing,
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
    references: list[str] | None = None,
):
    return log.emit(
        "DatasetAttestation",
        details={
            "statement": statement,
            "owner": owner,
            "references": references or [],
        },
        dataset_id=dataset_id,
        system="governance",
        actor=owner,
    )
