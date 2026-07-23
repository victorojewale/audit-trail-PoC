"""Human-in-the-loop governance events: approvals, waivers, attestations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .core import AuditLogger
from .registry import EventTypes

__all__ = ["record_approval", "record_waiver", "record_attestation"]

_SCOPE_KEYS = ("model_id", "dataset_id", "deployment_id")


def _scope(scope: Optional[Dict[str, Optional[str]]]) -> Dict[str, Optional[str]]:
    scope = scope or {}
    return {key: scope.get(key) or None for key in _SCOPE_KEYS}


def record_approval(
    log: AuditLogger,
    *,
    owner: str,
    rationale: str,
    scope: Dict[str, str],
    constraints: Optional[Dict[str, Any]] = None,
    references: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Record that a named owner approved a model, dataset or deployment."""
    return log.emit(
        EventTypes.APPROVAL,
        details={
            "decision": "approved",
            "rationale": rationale,
            "owner": owner,
            "constraints": constraints or {},
            "references": references or [],
        },
        system="governance",
        actor=owner,
        **_scope(scope),
    )


def record_waiver(
    log: AuditLogger,
    *,
    owner: str,
    rationale: str,
    scope: Dict[str, str],
    waived_controls: List[str],
    time_bound_until: Optional[str] = None,
    references: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Record that a named owner accepted the risk of skipping controls.

    Args:
        waived_controls: Identifiers of the controls not being applied.
        time_bound_until: RFC 3339 date after which the waiver lapses.
    """
    return log.emit(
        EventTypes.RISK_WAIVER,
        details={
            "decision": "waived",
            "rationale": rationale,
            "owner": owner,
            "waived_controls": waived_controls,
            "time_bound_until": time_bound_until,
            "references": references or [],
        },
        system="governance",
        actor=owner,
        **_scope(scope),
    )


def record_attestation(
    log: AuditLogger,
    *,
    owner: str,
    statement: str,
    scope: Dict[str, str],
    references: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Record a factual statement a named owner is standing behind."""
    return log.emit(
        EventTypes.ATTESTATION,
        details={
            "statement": statement,
            "owner": owner,
            "references": references or [],
        },
        system="governance",
        actor=owner,
        **_scope(scope),
    )
