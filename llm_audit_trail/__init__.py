from .core import AuditLogger, verify_log
from .hf import AuditTrailCallback, hf_audit_callback
from .decisions import record_approval, record_waiver, record_attestation

__all__ = [
    "AuditLogger",
    "verify_log",
    "AuditTrailCallback",
    "hf_audit_callback",
    "record_approval",
    "record_waiver",
    "record_attestation",
]

# Optional: in the sceernerio where fastapi is installed
try:
    from .fastapi import AuditMiddleware
    __all__.append("AuditMiddleware")
except Exception:
    AuditMiddleware = None  
