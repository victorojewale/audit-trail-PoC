"""Sources of known model/dataset/deployment identifiers.

The CLI uses these to offer recently seen identifiers instead of asking a
human to retype them, which is where typos silently fragment a ledger.
"""

from __future__ import annotations

import json
import os
from collections import deque
from typing import Any, Dict, List

__all__ = ["ScopeProvider", "JSONLLocalProvider", "load_scope_providers"]

_EMPTY: Dict[str, List[str]] = {"models": [], "datasets": [], "deployments": []}


class ScopeProvider:
    """Interface for anything that can list known identifiers."""

    def recent(self) -> Dict[str, List[str]]:
        return dict(_EMPTY)


class JSONLLocalProvider(ScopeProvider):
    """Reads identifiers from the tail of a local JSONL ledger."""

    def __init__(self, path: str, limit: int = 100) -> None:
        self.path = path
        self.limit = limit

    def recent(self) -> Dict[str, List[str]]:
        if not os.path.exists(self.path):
            return dict(_EMPTY)

        found: Dict[str, set] = {
            "models": set(),
            "datasets": set(),
            "deployments": set(),
        }
        key_for = {
            "model_id": "models",
            "dataset_id": "datasets",
            "deployment_id": "deployments",
        }

        with open(self.path, "r", encoding="utf-8") as fh:
            # deque keeps memory flat regardless of ledger size.
            tail = deque(fh, maxlen=self.limit)

        for line in tail:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            for field, bucket in key_for.items():
                value = record.get(field)
                if value:
                    found[bucket].add(value)

        return {bucket: sorted(values) for bucket, values in found.items()}


def load_scope_providers(config: Dict[str, Any]) -> List[ScopeProvider]:
    """Build the provider list for a resolved config."""
    return [
        JSONLLocalProvider(
            config.get("log_path") or "audit_trail.jsonl",
            limit=int(config.get("scan_limit", 100)),
        )
    ]
