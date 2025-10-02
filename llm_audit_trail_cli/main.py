import argparse, json, os, yaml
from typing import Any, Optional
from llm_audit_trail import AuditLogger
from llm_audit_trail.config import load_config
from llm_audit_trail.providers import load_scope_providers
from llm_audit_trail.decisions import record_approval, record_waiver, record_attestation

def _prompt(msg: str, default: Optional[str] = None) -> str:
    if default is not None and default != "":
        val = input(f"{msg} [{default}]: ").strip()
        return val or default
    return input(f"{msg}: ").strip()

def _prompt_json(msg: str, default_obj: Any) -> Any:
    default = json.dumps(default_obj)
    raw = input(f"{msg} (JSON) [{default}]: ").strip()
    if not raw:
        return default_obj
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"Invalid JSON, using default. Error: {e}")
        return default_obj

def _choose_from_list(title: str, options):
    if not options:
        return None
    print(f"{title}:")
    for i, v in enumerate(options, 1):
        print(f"  {i}. {v}")
    ans = input("Select number or Enter to skip: ").strip()
    if not ans:
        return None
    try:
        i = int(ans)
        if 1 <= i <= len(options):
            return options[i-1]
    except:
        pass
    print("Invalid selection; skipping.")
    return None

def load_decision_spec(event_type: str, cfg: dict) -> dict:
    for p in [cfg.get("decisions_path"), ".llm-audit/decisions.yaml",
              os.path.expanduser("~/.llm-audit/decisions.yaml"),
              "/etc/llm-audit/decisions.yaml"]:
        if p and os.path.exists(p):
            spec = yaml.safe_load(open(p, "r", encoding="utf-8")) or {}
            if event_type in spec:
                return spec[event_type]
    return {"fields": {}}

def interactive_decision(event_type: str, cfg: dict):
    providers = load_scope_providers(cfg)
    merged = {"models": set(), "datasets": set(), "deployments": set()}
    for pr in providers:
        r = pr.recent()
        for k in merged:
            merged[k].update(r.get(k, []))
    for k in merged:
        merged[k] = sorted(merged[k])

    spec = load_decision_spec(event_type, cfg)
    fields = spec.get("fields", {})
    values = {}

    def field_default(name, meta):
        if name == "owner":
            return cfg.get("owner")
        return meta.get("default")

    for name, meta in fields.items():
        prompt = meta.get("prompt", name)
        typ = meta.get("type", "str")
        default = field_default(name, meta)

        if name in ("model_id","dataset_id","deployment_id"):
            opts = merged["models"] if name=="model_id" else merged["datasets"] if name=="dataset_id" else merged["deployments"]
            pre = _choose_from_list(f"Recent {name}s", opts) or ""
            ans = _prompt(prompt, pre or default or "")
        elif typ == "json":
            ans = _prompt_json(prompt, default if default is not None else {})
        else:
            ans = _prompt(prompt, default)
        values[name] = ans

    log = AuditLogger(cfg.get("log_path", "audit_trail.jsonl"))
    scope = {k: values.get(k) or None for k in ("model_id","dataset_id","deployment_id")}

    if event_type == "Approval":
        return record_approval(
            log,
            owner=values.get("owner") or "Unknown",
            rationale=values.get("rationale") or "no rationale provided",
            scope=scope,
            constraints=values.get("constraints") or {},
            references=values.get("references") or [],
        )
    if event_type == "RiskWaiver":
        return record_waiver(
            log,
            owner=values.get("owner") or "Unknown",
            rationale=values.get("rationale") or "no rationale provided",
            scope=scope,
            waived_controls=values.get("waived_controls") or [],
            time_bound_until=values.get("time_bound_until") or None,
            references=values.get("references") or [],
        )
    if event_type == "Attestation":
        return record_attestation(
            log,
            owner=values.get("owner") or "Unknown",
            statement=values.get("statement") or "no statement provided",
            scope=scope,
            references=values.get("references") or [],
        )
    raise SystemExit(f"Unsupported event type: {event_type}")

def main():
    p = argparse.ArgumentParser(prog="llm-audit")
    p.add_argument("--config", help="Path to config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    for cmd in ("approve", "waive", "attest"):
        sub.add_parser(cmd, help=f"Interactive {cmd}").add_argument("--interactive", action="store_true")
    args = p.parse_args()
    cfg = load_config(args.config)

    if args.cmd == "approve":
        ev = interactive_decision("Approval", cfg)
    elif args.cmd == "waive":
        ev = interactive_decision("RiskWaiver", cfg)
    else:
        ev = interactive_decision("Attestation", cfg)

    print(json.dumps(ev, indent=2))

if __name__ == "__main__":
    main()
