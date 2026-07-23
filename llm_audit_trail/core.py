"""Append-only, hash-chained audit event log.

Threat model (read this before relying on the chain):

* The chain detects accidental corruption, in-place edits, deletions and
  reordering of events *within* the log.
* A plain SHA-256 chain does **not** stop an attacker who can write to the
  file: they can recompute every hash after editing. Set ``key=`` (or the
  ``AUDIT_HMAC_KEY`` environment variable) to switch to HMAC-SHA256 so
  re-chaining requires the secret.
* Deleting events from the *end* of the log is invisible to a self-contained
  chain. Persist an anchor (:func:`write_anchor`) somewhere the writer cannot
  reach and pass it to :func:`verify_log` as ``expected_head`` to detect it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional, Tuple, Union

__all__ = [
    "AuditLogger",
    "AuditLogError",
    "verify_log",
    "iter_events",
    "read_head",
    "write_anchor",
    "read_anchor",
    "DEFAULT_LOG_PATH",
    "SCHEMA_VERSION",
    "GENESIS",
]

GENESIS = "GENESIS"
SCHEMA_VERSION = "0.2.0"
DEFAULT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "audit_trail.jsonl")
HMAC_KEY_ENV = "AUDIT_HMAC_KEY"

_SHA256 = "sha256"
_HMAC_SHA256 = "hmac-sha256"


class AuditLogError(RuntimeError):
    """Raised when the ledger cannot be safely appended to or read."""


# --------------------------------------------------------------------------
# cross-process locking
# --------------------------------------------------------------------------

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

# Locked byte region sits far past any plausible ledger content so it never
# overlaps data we read or write.
_WIN_LOCK_OFFSET = 0x7FFFFFFF00000000


@contextmanager
def _file_lock(fh) -> Iterator[None]:
    """Exclusive advisory lock held for the whole read-then-append cycle.

    ``flock`` is per open file description, so separate handles on the same
    path block each other whether they come from different threads or
    different processes.
    """
    if fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return

    if msvcrt is not None:  # pragma: no cover - Windows only
        saved = fh.tell()
        fh.seek(_WIN_LOCK_OFFSET)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        try:
            fh.seek(saved)
            yield
        finally:
            fh.seek(_WIN_LOCK_OFFSET)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            fh.seek(saved)
        return

    yield  # pragma: no cover - no locking primitive available


# --------------------------------------------------------------------------
# serialisation helpers
# --------------------------------------------------------------------------


def _json_default(obj: Any) -> Any:
    """Coerce values json cannot encode (numpy scalars, dates, paths)."""
    item = getattr(obj, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:  # pragma: no cover - exotic .item() implementations
            pass
    return str(obj)


def _stable_json(obj: Dict[str, Any]) -> str:
    """Canonical form: the exact bytes that get hashed and written."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _resolve_key(key: Union[str, bytes, None]) -> Optional[bytes]:
    if key is None:
        key = os.environ.get(HMAC_KEY_ENV) or None
    if key is None:
        return None
    if isinstance(key, str):
        key = key.encode("utf-8")
    return key or None


def _digest(prev_hash: str, body: Dict[str, Any], key: Optional[bytes]) -> str:
    payload = (prev_hash + _stable_json(body)).encode("utf-8")
    if key is not None:
        return hmac.new(key, payload, hashlib.sha256).hexdigest()
    return hashlib.sha256(payload).hexdigest()


# --------------------------------------------------------------------------
# tail reading
# --------------------------------------------------------------------------


def _read_last_line(fh) -> Optional[bytes]:
    """Return the final non-empty line of a binary handle, or None if empty."""
    fh.seek(0, os.SEEK_END)
    pos = fh.tell()
    if pos == 0:
        return None

    buf = b""
    while pos > 0:
        step = min(8192, pos)
        pos -= step
        fh.seek(pos)
        buf = fh.read(step) + buf
        trimmed = buf.rstrip(b"\r\n")
        if not trimmed:
            return None  # file is nothing but newlines
        cut = trimmed.rfind(b"\n")
        if cut != -1:
            return trimmed[cut + 1 :].strip()
        if pos == 0:
            return trimmed.strip()
    return None  # pragma: no cover - unreachable


def _read_last_record(fh, path: str) -> Optional[Dict[str, Any]]:
    """Parse the last ledger entry.

    Refuses to continue on a corrupt tail: silently restarting the chain
    would hide exactly the damage this library exists to surface.
    """
    line = _read_last_line(fh)
    if line is None:
        return None
    try:
        record = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AuditLogError(
            f"{path}: final line is not valid JSON, refusing to append to a "
            f"corrupt ledger ({exc})"
        ) from exc
    if not isinstance(record, dict) or not isinstance(record.get("curr_hash"), str):
        raise AuditLogError(
            f"{path}: final line has no 'curr_hash', refusing to append to a "
            f"corrupt ledger"
        )
    return record


# --------------------------------------------------------------------------
# logger
# --------------------------------------------------------------------------


@dataclass
class AuditLogger:
    """Appends hash-chained events to a JSONL ledger.

    Safe to share across threads and processes: each append takes an
    exclusive lock covering the read-previous-hash / write-event cycle.

    Args:
        path: Ledger file. Parent directories are created on demand.
        system: Default ``system`` for emitted events (e.g. ``"fastapi"``).
        actor: Default ``actor`` for emitted events.
        key: HMAC secret. Defaults to ``$AUDIT_HMAC_KEY``; when unset the
            chain is a plain SHA-256 chain that anyone can recompute.
        fsync: Flush each event to disk before returning. Durable across
            power loss, roughly an order of magnitude slower.
    """

    path: str = DEFAULT_LOG_PATH
    system: Optional[str] = None
    actor: Optional[str] = None
    schema_version: str = SCHEMA_VERSION
    key: Union[str, bytes, None] = None
    fsync: bool = False
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        self.key = _resolve_key(self.key)
        parent = os.path.dirname(os.path.abspath(self.path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    def emit(
        self,
        event_type: str,
        details: Optional[Dict[str, Any]] = None,
        *,
        model_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
        deployment_id: Optional[str] = None,
        system: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append a single hash-chained audit event and return it."""
        with self._lock, open(self.path, "ab+") as fh, _file_lock(fh):
            previous = _read_last_record(fh, self.path)
            if previous is None:
                prev_hash, seq = GENESIS, 0
            else:
                prev_hash = previous["curr_hash"]
                prev_seq = previous.get("seq")
                seq = prev_seq + 1 if isinstance(prev_seq, int) else 0

            event: Dict[str, Any] = {
                "schema_version": self.schema_version,
                "seq": seq,
                "event_id": str(uuid.uuid4()),
                "timestamp": _now(),
                "event_type": event_type,
                "actor": actor if actor is not None else self.actor,
                "system": system if system is not None else self.system,
                "model_id": model_id,
                "dataset_id": dataset_id,
                "deployment_id": deployment_id,
                "details": details if details is not None else {},
                "hash_alg": _HMAC_SHA256 if self.key else _SHA256,
                "prev_hash": prev_hash,
            }
            event["curr_hash"] = _digest(prev_hash, event, self.key)  # type: ignore[arg-type]

            fh.seek(0, os.SEEK_END)
            fh.write((_stable_json(event) + "\n").encode("utf-8"))
            fh.flush()
            if self.fsync:
                os.fsync(fh.fileno())

        return event

    def head(self) -> Optional[Dict[str, Any]]:
        """Current chain head, or None for an empty ledger."""
        return read_head(self.path)

    def verify(self, **kwargs: Any) -> Tuple[bool, Dict[str, Any]]:
        """Verify this ledger. See :func:`verify_log`."""
        kwargs.setdefault("key", self.key)
        return verify_log(self.path, **kwargs)


# --------------------------------------------------------------------------
# reading and verification
# --------------------------------------------------------------------------


def iter_events(path: str = DEFAULT_LOG_PATH) -> Iterator[Dict[str, Any]]:
    """Yield each event in the ledger. Blank lines are skipped."""
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def read_head(path: str = DEFAULT_LOG_PATH) -> Optional[Dict[str, Any]]:
    """Read the chain head without scanning the whole ledger."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    with open(path, "rb") as fh, _file_lock(fh):
        record = _read_last_record(fh, path)
    if record is None:
        return None
    return {
        "seq": record.get("seq"),
        "hash": record["curr_hash"],
        "timestamp": record.get("timestamp"),
    }


def write_anchor(
    path: str = DEFAULT_LOG_PATH, anchor_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Record the current head so later truncation becomes detectable.

    An anchor only helps if it is stored where whoever writes the ledger
    cannot quietly rewrite it too — a different host, an append-only bucket,
    a signed commit, a ticket.
    """
    head = read_head(path)
    if head is None:
        return None
    anchor = dict(head, path=os.path.abspath(path), anchored_at=_now())
    target = anchor_path or (path + ".anchor")
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(anchor, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return anchor


def read_anchor(anchor_path: str) -> Dict[str, Any]:
    """Load an anchor previously written by :func:`write_anchor`."""
    with open(anchor_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def verify_log(
    path: str = DEFAULT_LOG_PATH,
    *,
    key: Union[str, bytes, None] = None,
    expected_head: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Verify the hash chain end to end.

    Never raises for bad input: unreadable, truncated and malformed ledgers
    all come back as ``(False, report)``.

    Args:
        path: Ledger to verify.
        key: HMAC secret for keyed ledgers. Defaults to ``$AUDIT_HMAC_KEY``.
        expected_head: An anchor from :func:`write_anchor`. Verification then
            also requires that the anchored event is still present at its
            original sequence number with its original hash, which is what
            catches truncation of the ledger's tail.

    Returns:
        ``(ok, report)``. On success the report carries ``events`` and
        ``head``; on failure it carries an ``error`` code plus context.
    """
    key = _resolve_key(key)
    prev_hash = GENESIS
    prev_seq: Optional[int] = None
    count = 0
    last: Optional[Dict[str, Any]] = None
    anchor_seen = expected_head is None

    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError as exc:
        return False, {"error": "unreadable", "path": path, "detail": str(exc)}

    with handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except ValueError as exc:
                return False, {
                    "error": "malformed_json",
                    "line": line_no,
                    "detail": str(exc),
                }
            if not isinstance(record, dict):
                return False, {"error": "malformed_record", "line": line_no}

            claimed = record.get("curr_hash")
            if not isinstance(claimed, str):
                return False, {
                    "error": "missing_curr_hash",
                    "line": line_no,
                    "event_id": record.get("event_id"),
                }

            if record.get("prev_hash") != prev_hash:
                return False, {
                    "error": "broken_link",
                    "line": line_no,
                    "event_id": record.get("event_id"),
                    "expected_prev_hash": prev_hash,
                    "found_prev_hash": record.get("prev_hash"),
                    "detail": "an event was deleted, reordered or inserted here",
                }

            alg = record.get("hash_alg", _SHA256)
            if alg not in (_SHA256, _HMAC_SHA256):
                return False, {
                    "error": "unknown_hash_alg",
                    "line": line_no,
                    "hash_alg": alg,
                }
            if alg == _HMAC_SHA256 and key is None:
                return False, {
                    "error": "key_required",
                    "line": line_no,
                    "detail": (
                        "ledger is HMAC-chained; pass key= or set "
                        f"${HMAC_KEY_ENV}"
                    ),
                }

            body = {k: v for k, v in record.items() if k != "curr_hash"}
            calculated = _digest(prev_hash, body, key if alg == _HMAC_SHA256 else None)
            if not hmac.compare_digest(calculated, claimed):
                return False, {
                    "error": "hash_mismatch",
                    "line": line_no,
                    "event_id": record.get("event_id"),
                    "expected": calculated,
                    "found": claimed,
                    "detail": "this event's contents were modified after it was written",
                }

            seq = record.get("seq")
            if isinstance(seq, int):
                if prev_seq is not None and seq != prev_seq + 1:
                    return False, {
                        "error": "seq_gap",
                        "line": line_no,
                        "expected_seq": prev_seq + 1,
                        "found_seq": seq,
                    }
                prev_seq = seq
                if not anchor_seen and seq == expected_head.get("seq"):  # type: ignore[union-attr]
                    if claimed != expected_head.get("hash"):  # type: ignore[union-attr]
                        return False, {
                            "error": "anchor_mismatch",
                            "line": line_no,
                            "seq": seq,
                            "expected": expected_head.get("hash"),  # type: ignore[union-attr]
                            "found": claimed,
                            "detail": "the anchored event was rewritten",
                        }
                    anchor_seen = True

            prev_hash = claimed
            last = record
            count += 1

    head = (
        {"seq": last.get("seq"), "hash": last["curr_hash"], "timestamp": last.get("timestamp")}
        if last is not None
        else None
    )

    if not anchor_seen:
        return False, {
            "error": "anchor_missing",
            "detail": (
                "the anchored event is no longer in the ledger; its tail was "
                "truncated or rewritten"
            ),
            "expected_head": expected_head,
            "events": count,
            "head": head,
        }

    return True, {"events": count, "head": head}
