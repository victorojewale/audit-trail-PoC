"""Layered configuration for the CLI.

Precedence, lowest to highest: built-in defaults, ``/etc/llm-audit``, the
user's home directory, the current project, an explicit ``--config`` path,
then environment variables.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import yaml

__all__ = ["DEFAULTS", "SEARCH_PATHS", "load_config"]

DEFAULTS: Dict[str, Any] = {
    "log_path": "audit_trail.jsonl",
    "scan_limit": 100,
    "owner": None,
    "decisions_path": None,
}

SEARCH_PATHS: List[str] = [
    "/etc/llm-audit/config.yaml",
    os.path.expanduser("~/.llm-audit/config.yaml"),
    ".llm-audit/config.yaml",
]

_ENV_OVERRIDES = {
    "log_path": "AUDIT_LOG_PATH",
    "owner": "AUDIT_OWNER",
}


def load_config(extra_path: Optional[str] = None) -> Dict[str, Any]:
    """Merge config files and environment variables into a single mapping."""
    config = dict(DEFAULTS)

    for path in SEARCH_PATHS + ([extra_path] if extra_path else []):
        if not path or not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if isinstance(loaded, dict):
            config.update(loaded)

    for key, env_var in _ENV_OVERRIDES.items():
        value = os.environ.get(env_var)
        if value:
            config[key] = value

    return config
