
from __future__ import annotations
from typing import Dict, Any, Optional, List
from .core import AuditLogger

def record_approval(
    log: AuditLogger,
    *,
    owner: str,
    rationale: str,
    scope: Dict[str, str],
    constraints: Optional[Dict[str, Any]] = None,
    references: Optional[List[str]] = None,
):
    return log.emit(
        "Approval",
        details={
            "decision": "approved",
            "rationale": rationale,
            "owner": owner,
            "constraints": constraints or {},
            "references": references or [],
        },
        model_id=scope.get("model_id"),
        dataset_id=scope.get("dataset_id"),
        deployment_id=scope.get("deployment_id"),
        system="governance",
        actor=owner,
    )

def record_waiver(
    log: AuditLogger,
    *,
    owner: str,
    rationale: str,
    scope: Dict[str, str],
    waived_controls: List[str],
    time_bound_until: Optional[str] = None,  # RFC3339 date if applicable
    references: Optional[List[str]] = None,
):
    return log.emit(
        "RiskWaiver",
        details={
            "decision": "waived",
            "rationale": rationale,
            "owner": owner,
            "waived_controls": waived_controls,
            "time_bound_until": time_bound_until,
            "references": references or [],
        },
        model_id=scope.get("model_id"),
        dataset_id=scope.get("dataset_id"),
        deployment_id=scope.get("deployment_id"),
        system="governance",
        actor=owner,
    )

def record_attestation(
    log: AuditLogger,
    *,
    owner: str,
    statement: str,
    scope: Dict[str, str],
    references: Optional[List[str]] = None,
):
    return log.emit(
        "Attestation",
        details={
            "statement": statement,
            "owner": owner,
            "references": references or [],
        },
        model_id=scope.get("model_id"),
        dataset_id=scope.get("dataset_id"),
        deployment_id=scope.get("deployment_id"),
        system="governance",
        actor=owner,
    )
