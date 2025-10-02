from __future__ import annotations
import os, json
from typing import Dict, List

class ScopeProvider:
    def recent(self) -> Dict[str, List[str]]:
        return {"models": [], "datasets": [], "deployments": []}

class JSONLLocalProvider(ScopeProvider):
    def __init__(self, path: str, limit: int = 100):
        self.path = path
        self.limit = limit

    def recent(self) -> Dict[str, List[str]]:
        models, datasets, deployments = set(), set(), set()
        if not os.path.exists(self.path):
            return {"models": [], "datasets": [], "deployments": []}
        with open(self.path, "r", encoding="utf-8") as f:
            lines = list(f)[-self.limit:]
        for line in lines:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            mid = rec.get("model_id")
            did = rec.get("dataset_id")
            dep = rec.get("deployment_id")
            if mid: models.add(mid)
            if did: datasets.add(did)
            if dep: deployments.add(dep)
        return {
            "models": sorted(models),
            "datasets": sorted(datasets),
            "deployments": sorted(deployments),
        }

def load_scope_providers(cfg: dict) -> list[ScopeProvider]:
    return [JSONLLocalProvider(cfg.get("log_path", "audit_trail.jsonl"),
                               limit=int(cfg.get("scan_limit", 100)))]
