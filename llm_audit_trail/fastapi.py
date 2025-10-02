
from __future__ import annotations
from starlette.middleware.base import BaseHTTPMiddleware
import time, hashlib
from .core import AuditLogger

def _hash16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

class AuditMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware that logs request/response metadata."""
    def __init__(self, app, logger: AuditLogger, redact_previews: bool = True, model_id: str | None = None):
        super().__init__(app)
        self.log = logger
        self.redact = redact_previews
        self.model_id = model_id

    async def dispatch(self, request, call_next):
        t0 = time.time()
        body = await request.body()
        body_text = body.decode("utf-8", errors="ignore")
        body_preview = body_text[:64]
        req_id = _hash16(f"{time.time()}::{body_preview}")

        self.log.emit("InferenceRequest", {
            "request_id": req_id,
            "path": str(request.url.path),
            "method": request.method,
            "client_ip": request.client.host if request.client else None,
            "body_preview": None if self.redact else body_preview,
            "body_hash": _hash16(body_text)
        }, system="fastapi", model_id=self.model_id)

        response = await call_next(request)
        latency_ms = int((time.time() - t0) * 1000)

        # capture body
        chunks = [chunk async for chunk in response.body_iterator]
        response.body_iterator = iter(chunks)
        resp_bytes = b"".join(chunks)
        resp_text = resp_bytes.decode("utf-8", errors="ignore")

        self.log.emit("InferenceResponse", {
            "request_id": req_id,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "resp_preview": None if self.redact else resp_text[:64],
            "resp_hash": _hash16(resp_text)
        }, system="fastapi", model_id=self.model_id)

        return response
