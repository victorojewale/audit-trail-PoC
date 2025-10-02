
import argparse, json, os, sys, tempfile, subprocess
from typing import Dict, Any, List, Optional
from llm_audit_trail import AuditLogger
from llm_audit_trail.decisions import record_approval, record_waiver, record_attestation

DEFAULT_LOG = os.environ.get("AUDIT_LOG_PATH", "audit_trail.jsonl")

def _load_recent_ids(path: str = DEFAULT_LOG, limit: int = 50):
    models, datasets, deployments = set(), set(), set()
    if not os.path.exists(path):
        return [], [], []
    with open(path, "r", encoding="utf-8") as f:
        for line in list(f)[-limit:]:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("model_id"):
                models.add(rec["model_id"])
            if rec.get("dataset_id"):
                datasets.add(rec["dataset_id"])
            if rec.get("deployment_id"):
                deployments.add(rec["deployment_id"])
    return sorted(models), sorted(datasets), sorted(deployments)

def _prompt(msg: str, default: Optional[str] = None) -> str:
    if default:
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

def _choose_from_list(title: str, options: List[str]) -> Optional[str]:
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

def interactive_approval(log: AuditLogger):
    models, datasets, deployments = _load_recent_ids()
    owner = _prompt("Owner (person or committee)", os.environ.get("AUDIT_OWNER"))
    rationale = _prompt("Rationale", "Meets acceptance criteria")
    model_id = _prompt("Model ID", _choose_from_list("Recent model_ids", models) or "")
    dataset_id = _prompt("Dataset ID", _choose_from_list("Recent dataset_ids", datasets) or "")
    deployment_id = _prompt("Deployment ID", _choose_from_list("Recent deployment_ids", deployments) or "")
    constraints = _prompt_json("Constraints", {"rollout":"10% for 48h"})
    references = _prompt_json("References", [])
    ev = record_approval(
        log, owner=owner, rationale=rationale,
        scope={"model_id": model_id or None, "dataset_id": dataset_id or None, "deployment_id": deployment_id or None},
        constraints=constraints, references=references
    )
    print(json.dumps(ev, indent=2))

def interactive_waiver(log: AuditLogger):
    models, datasets, deployments = _load_recent_ids()
    owner = _prompt("Owner", os.environ.get("AUDIT_OWNER"))
    rationale = _prompt("Rationale", "Pilot exception")
    model_id = _prompt("Model ID", _choose_from_list("Recent model_ids", models) or "")
    dataset_id = _prompt("Dataset ID", _choose_from_list("Recent dataset_ids", datasets) or "")
    deployment_id = _prompt("Deployment ID", _choose_from_list("Recent deployment_ids", deployments) or "")
    waived_controls = _prompt_json("Waived controls", ["SLO:latency_p95"])
    time_bound_until = _prompt("Time bound until (RFC3339) or blank", "")
    references = _prompt_json("References", [])
    ev = record_waiver(
        log, owner=owner, rationale=rationale,
        scope={"model_id": model_id or None, "dataset_id": dataset_id or None, "deployment_id": deployment_id or None},
        waived_controls=waived_controls, time_bound_until=(time_bound_until or None),
        references=references
    )
    print(json.dumps(ev, indent=2))

def interactive_attestation(log: AuditLogger):
    models, datasets, deployments = _load_recent_ids()
    owner = _prompt("Owner", os.environ.get("AUDIT_OWNER") or "Compliance")
    statement = _prompt("Statement", "Data licensed and within scope")
    model_id = _prompt("Model ID", _choose_from_list("Recent model_ids", models) or "")
    dataset_id = _prompt("Dataset ID", _choose_from_list("Recent dataset_ids", datasets) or "")
    deployment_id = _prompt("Deployment ID", _choose_from_list("Recent deployment_ids", deployments) or "")
    references = _prompt_json("References", [])
    ev = record_attestation(
        log, owner=owner, statement=statement,
        scope={"model_id": model_id or None, "dataset_id": dataset_id or None, "deployment_id": deployment_id or None},
        references=references
    )
    print(json.dumps(ev, indent=2))

def main():
    p = argparse.ArgumentParser(prog="llm-audit")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("approve", help="Record an approval decision")
    a.add_argument("--owner")
    a.add_argument("--rationale")
    a.add_argument("--model-id")
    a.add_argument("--dataset-id")
    a.add_argument("--deployment-id")
    a.add_argument("--constraints", help="JSON dict")
    a.add_argument("--references", help="JSON list")
    a.add_argument("--interactive", action="store_true")

    w = sub.add_parser("waive", help="Record a risk waiver decision")
    w.add_argument("--owner")
    w.add_argument("--rationale")
    w.add_argument("--waived-controls", help="JSON list")
    w.add_argument("--time-bound-until")
    w.add_argument("--model-id")
    w.add_argument("--dataset-id")
    w.add_argument("--deployment-id")
    w.add_argument("--references", help="JSON list")
    w.add_argument("--interactive", action="store_true")

    t = sub.add_parser("attest", help="Record an attestation")
    t.add_argument("--owner")
    t.add_argument("--statement")
    t.add_argument("--model-id")
    t.add_argument("--dataset-id")
    t.add_argument("--deployment-id")
    t.add_argument("--references", help="JSON list")
    t.add_argument("--interactive", action="store_true")

    args = p.parse_args()
    log = AuditLogger()

    if args.cmd == "approve":
        if args.interactive:
            return interactive_approval(log)
        ev = record_approval(
            log,
            owner=args.owner or os.environ.get("AUDIT_OWNER") or "Unknown",
            rationale=args.rationale or "no rationale provided",
            scope={"model_id": args.model_id, "dataset_id": args.dataset_id, "deployment_id": args.deployment_id},
            constraints=json.loads(args.constraints) if args.constraints else {},
            references=json.loads(args.references) if args.references else [],
        )
    elif args.cmd == "waive":
        if args.interactive:
            return interactive_waiver(log)
        ev = record_waiver(
            log,
            owner=args.owner or os.environ.get("AUDIT_OWNER") or "Unknown",
            rationale=args.rationale or "no rationale provided",
            scope={"model_id": args.model_id, "dataset_id": args.dataset_id, "deployment_id": args.deployment_id},
            waived_controls=json.loads(args.waived_controls) if args.waived_controls else [],
            time_bound_until=args.time_bound_until,
            references=json.loads(args.references) if args.references else [],
        )
    else:
        if args.interactive:
            return interactive_attestation(log)
        ev = record_attestation(
            log,
            owner=args.owner or os.environ.get("AUDIT_OWNER") or "Unknown",
            statement=args.statement or "no statement provided",
            scope={"model_id": args.model_id, "dataset_id": args.dataset_id, "deployment_id": args.deployment_id},
            references=json.loads(args.references) if args.references else [],
        )
    print(json.dumps(ev, indent=2))

if __name__ == "__main__":
    main()
