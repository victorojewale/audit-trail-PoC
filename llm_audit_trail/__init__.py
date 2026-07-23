"""Tamper-evident audit trails for LLM lifecycles.

Only the standard library is required for the core logger and verifier.
Framework integrations are optional extras and are imported lazily, so
``import llm_audit_trail`` never pulls in transformers, fastapi or starlette.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .core import (
    DEFAULT_LOG_PATH,
    GENESIS,
    SCHEMA_VERSION,
    AuditLogError,
    AuditLogger,
    iter_events,
    read_anchor,
    read_head,
    verify_log,
    write_anchor,
)
from .datasets import dataset_attestation, register_dataset
from .decisions import record_approval, record_attestation, record_waiver
from .registry import EventTypes

__all__ = [
    "__version__",
    "AuditLogger",
    "AuditLogError",
    "verify_log",
    "iter_events",
    "read_head",
    "write_anchor",
    "read_anchor",
    "register_dataset",
    "dataset_attestation",
    "record_approval",
    "record_waiver",
    "record_attestation",
    "EventTypes",
    "DEFAULT_LOG_PATH",
    "SCHEMA_VERSION",
    "GENESIS",
    "AuditTrailCallback",
    "hf_audit_callback",
    "AuditMiddleware",
]


def _missing(name: str, extra: str, cause: ImportError):
    """Stand in for an integration whose optional dependency is absent.

    Raising on use — rather than at import time — keeps the core usable while
    still telling the caller exactly which extra to install.
    """

    def _raise(*_args, **_kwargs):
        raise ImportError(
            f"{name} requires the '{extra}' extra: "
            f"pip install 'llm-audit-trail[{extra}]'"
        ) from cause

    return _raise


try:
    from .hf import AuditTrailCallback, hf_audit_callback
except ImportError as _hf_error:  # transformers not installed
    AuditTrailCallback = _missing("AuditTrailCallback", "hf", _hf_error)  # type: ignore[assignment]
    hf_audit_callback = _missing("hf_audit_callback", "hf", _hf_error)  # type: ignore[assignment]

try:
    from .fastapi import AuditMiddleware
except ImportError as _api_error:  # starlette/fastapi not installed
    AuditMiddleware = _missing("AuditMiddleware", "fastapi", _api_error)  # type: ignore[assignment]
