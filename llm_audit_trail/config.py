from __future__ import annotations
import os, yaml

DEFAULTS = {
    "log_path": os.environ.get("AUDIT_LOG_PATH", "audit_trail.jsonl"),
    "scan_limit": 100,
    "owner": os.environ.get("AUDIT_OWNER"),
}

SEARCH_PATHS = [
    "/etc/llm-audit/config.yaml",
    os.path.expanduser("~/.llm-audit/config.yaml"),
    ".llm-audit/config.yaml",
]

def load_config(extra_path: str | None = None) -> dict:
    cfg = dict(DEFAULTS)
    for p in SEARCH_PATHS + ([extra_path] if extra_path else []):
        if p and os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
                if not isinstance(loaded, dict):
                    continue
                cfg.update(loaded)
    if os.environ.get("AUDIT_LOG_PATH"):
        cfg["log_path"] = os.environ["AUDIT_LOG_PATH"]
    if os.environ.get("AUDIT_OWNER"):
        cfg["owner"] = os.environ["AUDIT_OWNER"]
    return cfg
