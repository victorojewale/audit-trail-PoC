"""Starlette/FastAPI middleware that records inference request metadata."""

from __future__ import annotations

import hashlib
import time
import uuid
from functools import partial
from typing import Optional

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from .core import AuditLogger

__all__ = ["AuditMiddleware"]


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class AuditMiddleware(BaseHTTPMiddleware):
    """Log request/response metadata for every call through the app.

    Args:
        logger: Where events are written.
        redact_previews: Keep request/response bodies out of the ledger and
            record only their hashes. On by default; prompts and completions
            are usually the most sensitive thing an endpoint handles.
        model_id: Stamped on every emitted event.
        log_client_ip: Record the caller's IP. Off by default because an IP
            is personal data in most jurisdictions, and an audit ledger is
            append-only by design.
        preview_chars: Length of the stored preview when not redacting.
        buffer_response: Read the response body to hash it. Set False for
            streaming endpoints (SSE, token streaming) — the response then
            passes straight through and its hash is recorded as None.
    """

    def __init__(
        self,
        app,
        logger: AuditLogger,
        redact_previews: bool = True,
        model_id: Optional[str] = None,
        log_client_ip: bool = False,
        preview_chars: int = 64,
        buffer_response: bool = True,
    ) -> None:
        super().__init__(app)
        self.log = logger
        self.redact = redact_previews
        self.model_id = model_id
        self.log_client_ip = log_client_ip
        self.preview_chars = preview_chars
        self.buffer_response = buffer_response

    def _preview(self, text: str) -> Optional[str]:
        return None if self.redact else text[: self.preview_chars]

    async def _emit(self, event_type: str, details: dict) -> None:
        # emit() takes an exclusive file lock; run it off the event loop so a
        # slow or contended ledger cannot stall unrelated requests.
        await run_in_threadpool(
            partial(
                self.log.emit,
                event_type,
                details,
                system="fastapi",
                model_id=self.model_id,
            )
        )

    async def dispatch(self, request, call_next):
        started = time.perf_counter()
        request_id = uuid.uuid4().hex

        body = await request.body()
        body_text = body.decode("utf-8", errors="replace")

        details = {
            "request_id": request_id,
            "path": str(request.url.path),
            "method": request.method,
            "body_bytes": len(body),
            "body_preview": self._preview(body_text),
            "body_hash": _sha256(body),
        }
        if self.log_client_ip:
            details["client_ip"] = request.client.host if request.client else None
        await self._emit("InferenceRequest", details)

        response = await call_next(request)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)

        if not self.buffer_response:
            await self._emit(
                "InferenceResponse",
                {
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "resp_preview": None,
                    "resp_hash": None,
                    "streamed": True,
                },
            )
            return response

        chunks = [chunk async for chunk in response.body_iterator]
        payload = b"".join(
            chunk.encode("utf-8") if isinstance(chunk, str) else chunk
            for chunk in chunks
        )

        async def replay():
            # body_iterator is consumed with `async for`; a plain iterator
            # here raises TypeError before the client sees a response.
            for chunk in chunks:
                yield chunk

        response.body_iterator = replay()

        await self._emit(
            "InferenceResponse",
            {
                "request_id": request_id,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "resp_bytes": len(payload),
                "resp_preview": self._preview(payload.decode("utf-8", errors="replace")),
                "resp_hash": _sha256(payload),
                "streamed": False,
            },
        )
        return response
