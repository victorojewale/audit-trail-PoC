
from __future__ import annotations
import hashlib, json, os, time, uuid
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple


DEFAULT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "audit_trail.jsonl")

def _stable_json(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _last_hash(path: str) -> str:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return "GENESIS"
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        buf = bytearray()
        while size:
            size -= 1
            f.seek(size)
            b = f.read(1)
            if b == b"\n" and buf:
                break
            buf.extend(b)
    line = bytes(reversed(buf)).decode("utf-8").strip()
    try:
        rec = json.loads(line)
        return rec["curr_hash"]
    except Exception:
        return "GENESIS"

@dataclass
class AuditLogger:
    path: str = DEFAULT_LOG_PATH
    system: Optional[str] = None
    actor: Optional[str] = None
    schema_version: str = "0.1.0"

    def emit(
        self,
        event_type: str,
        details: Dict[str, Any],
        *,
        model_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
        deployment_id: Optional[str] = None,
        system: Optional[str] = None,
        actor: Optional[str] = None
    ) -> Dict[str, Any]:
        """Write a single audit event with hash-chaining."""
        prev_hash = _last_hash(self.path)
        event: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "event_id": str(uuid.uuid4()),
            "timestamp": _now(),
            "event_type": event_type,
            "actor": actor if actor is not None else self.actor,
            "system": system if system is not None else self.system,
            "model_id": model_id,
            "dataset_id": dataset_id,
            "deployment_id": deployment_id,
            "details": details,
            "prev_hash": prev_hash,
        }
        payload = prev_hash + _stable_json(event)
        event["curr_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(_stable_json(event) + "\n")
        return event

# verification utility
def verify_log(path: str = DEFAULT_LOG_PATH) -> Tuple[bool, Optional[Dict[str, Any]]]:
    prev = "GENESIS"
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            rec = json.loads(line)
            claimed = rec["curr_hash"]
            calc = hashlib.sha256((prev + _stable_json({k: rec[k] for k in rec if k != "curr_hash"})).encode("utf-8")).hexdigest()
            if calc != claimed:
                return False, {"line": i, "event_id": rec.get("event_id"), "expected": calc, "found": claimed}
            prev = claimed
    return True, None
