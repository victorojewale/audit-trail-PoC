"""``llm-audit`` command line entry point.

Governance decisions belong to people, not to training scripts, so they are
recorded here rather than through the library API. Every subcommand works
both interactively and from flags, so the same tool serves a human at a
terminal and a CI job.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

import yaml

from llm_audit_trail import (
    AuditLogger,
    read_anchor,
    record_approval,
    record_attestation,
    record_waiver,
    verify_log,
    write_anchor,
)
from llm_audit_trail.config import load_config
from llm_audit_trail.providers import load_scope_providers

SCOPE_FIELDS = ("model_id", "dataset_id", "deployment_id")

# Used when no decisions.yaml is found. Deliberately carries no default
# rationale or statement: an audit trail should never invent the reason a
# human gave for a decision.
DEFAULT_DECISION_SPEC: Dict[str, Dict[str, Any]] = {
    "Approval": {
        "fields": {
            "owner": {"prompt": "Owner (person or committee)", "required": True},
            "rationale": {"prompt": "Rationale", "required": True},
            "model_id": {"prompt": "Model ID"},
            "dataset_id": {"prompt": "Dataset ID"},
            "deployment_id": {"prompt": "Deployment ID"},
            "constraints": {"prompt": "Constraints", "type": "json", "default": {}},
            "references": {"prompt": "References", "type": "json", "default": []},
        }
    },
    "RiskWaiver": {
        "fields": {
            "owner": {"prompt": "Owner", "required": True},
            "rationale": {"prompt": "Rationale", "required": True},
            "model_id": {"prompt": "Model ID"},
            "dataset_id": {"prompt": "Dataset ID"},
            "deployment_id": {"prompt": "Deployment ID"},
            "waived_controls": {
                "prompt": "Waived controls",
                "type": "json",
                "default": [],
                "required": True,
            },
            "time_bound_until": {"prompt": "Time bound until (RFC 3339)"},
            "references": {"prompt": "References", "type": "json", "default": []},
        }
    },
    "Attestation": {
        "fields": {
            "owner": {"prompt": "Owner", "required": True},
            "statement": {"prompt": "Statement", "required": True},
            "model_id": {"prompt": "Model ID"},
            "dataset_id": {"prompt": "Dataset ID"},
            "deployment_id": {"prompt": "Deployment ID"},
            "references": {"prompt": "References", "type": "json", "default": []},
        }
    },
}


class CliError(Exception):
    """A user-facing error; printed without a traceback."""


# --------------------------------------------------------------------------
# prompting
# --------------------------------------------------------------------------


def _prompt(message: str, default: Optional[str] = None) -> str:
    if default:
        return input(f"{message} [{default}]: ").strip() or default
    return input(f"{message}: ").strip()


def _prompt_json(message: str, default: Any) -> Any:
    raw = input(f"{message} (JSON) [{json.dumps(default)}]: ").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError as exc:
        print(f"  invalid JSON ({exc}); keeping the default", file=sys.stderr)
        return default


def _choose(title: str, options: List[str]) -> Optional[str]:
    if not options:
        return None
    print(f"{title}:")
    for index, value in enumerate(options, 1):
        print(f"  {index}. {value}")
    answer = input("Select a number, or press Enter to skip: ").strip()
    if not answer:
        return None
    try:
        index = int(answer)
    except ValueError:
        print("  not a number; skipping", file=sys.stderr)
        return None
    if 1 <= index <= len(options):
        return options[index - 1]
    print("  out of range; skipping", file=sys.stderr)
    return None


# --------------------------------------------------------------------------
# decision specs and scope discovery
# --------------------------------------------------------------------------


def load_decision_spec(event_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Find the field spec for an event type, falling back to the built-in."""
    candidates = [
        config.get("decisions_path"),
        ".llm-audit/decisions.yaml",
        os.path.expanduser("~/.llm-audit/decisions.yaml"),
        "/etc/llm-audit/decisions.yaml",
    ]
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            spec = yaml.safe_load(fh) or {}
        if isinstance(spec, dict) and event_type in spec:
            return spec[event_type]
    return DEFAULT_DECISION_SPEC.get(event_type, {"fields": {}})


def _recent_scopes(config: Dict[str, Any]) -> Dict[str, List[str]]:
    merged: Dict[str, set] = {"models": set(), "datasets": set(), "deployments": set()}
    for provider in load_scope_providers(config):
        recent = provider.recent()
        for key in merged:
            merged[key].update(recent.get(key, []))
    return {key: sorted(value) for key, value in merged.items()}


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _fill_interactively(
    event_type: str, values: Dict[str, Any], config: Dict[str, Any]
) -> Dict[str, Any]:
    """Prompt for every field the caller left blank."""
    spec = load_decision_spec(event_type, config)
    fields = spec.get("fields", {})
    scopes = _recent_scopes(config)
    scope_options = {
        "model_id": scopes["models"],
        "dataset_id": scopes["datasets"],
        "deployment_id": scopes["deployments"],
    }

    for name, meta in fields.items():
        if not _is_blank(values.get(name)):
            continue
        prompt = meta.get("prompt", name)
        default = config.get("owner") if name == "owner" else meta.get("default")

        if name in SCOPE_FIELDS:
            picked = _choose(f"Recent {name}s", scope_options[name])
            values[name] = _prompt(prompt, picked or default or "") or None
        elif meta.get("type") == "json":
            values[name] = _prompt_json(prompt, default if default is not None else {})
        else:
            values[name] = _prompt(prompt, default) or None

    return values


def _require(values: Dict[str, Any], event_type: str, names: List[str]) -> None:
    missing = [name for name in names if _is_blank(values.get(name))]
    if missing:
        raise CliError(
            f"{event_type} needs {', '.join(missing)}. "
            f"Pass them as flags, or re-run with --interactive."
        )


def _wants_interactive(args, values: Dict[str, Any], required: List[str]) -> bool:
    if getattr(args, "interactive", False):
        return True
    if getattr(args, "no_interactive", False):
        return False
    incomplete = any(_is_blank(values.get(name)) for name in required)
    return incomplete and sys.stdin.isatty()


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------


def _logger(args, config: Dict[str, Any]) -> AuditLogger:
    return AuditLogger(path=args.log_path or config.get("log_path"))


def _scope_of(values: Dict[str, Any]) -> Dict[str, Any]:
    return {name: values.get(name) or None for name in SCOPE_FIELDS}


def cmd_approve(args, config: Dict[str, Any]) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "owner": args.owner or config.get("owner"),
        "rationale": args.rationale,
        "constraints": json.loads(args.constraints) if args.constraints else {},
        "references": args.reference or [],
        **{name: getattr(args, name) for name in SCOPE_FIELDS},
    }
    if _wants_interactive(args, values, ["owner", "rationale"]):
        values = _fill_interactively("Approval", values, config)
    _require(values, "Approval", ["owner", "rationale"])

    return record_approval(
        _logger(args, config),
        owner=values["owner"],
        rationale=values["rationale"],
        scope=_scope_of(values),
        constraints=values.get("constraints") or {},
        references=values.get("references") or [],
    )


def cmd_waive(args, config: Dict[str, Any]) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "owner": args.owner or config.get("owner"),
        "rationale": args.rationale,
        "waived_controls": args.waived_control or [],
        "time_bound_until": args.until,
        "references": args.reference or [],
        **{name: getattr(args, name) for name in SCOPE_FIELDS},
    }
    required = ["owner", "rationale", "waived_controls"]
    if _wants_interactive(args, values, required):
        values = _fill_interactively("RiskWaiver", values, config)
    _require(values, "RiskWaiver", required)

    controls = values["waived_controls"]
    if isinstance(controls, str):
        controls = [controls]

    return record_waiver(
        _logger(args, config),
        owner=values["owner"],
        rationale=values["rationale"],
        scope=_scope_of(values),
        waived_controls=list(controls),
        time_bound_until=values.get("time_bound_until") or None,
        references=values.get("references") or [],
    )


def cmd_attest(args, config: Dict[str, Any]) -> Dict[str, Any]:
    values: Dict[str, Any] = {
        "owner": args.owner or config.get("owner"),
        "statement": args.statement,
        "references": args.reference or [],
        **{name: getattr(args, name) for name in SCOPE_FIELDS},
    }
    if _wants_interactive(args, values, ["owner", "statement"]):
        values = _fill_interactively("Attestation", values, config)
    _require(values, "Attestation", ["owner", "statement"])

    return record_attestation(
        _logger(args, config),
        owner=values["owner"],
        statement=values["statement"],
        scope=_scope_of(values),
        references=values.get("references") or [],
    )


def cmd_verify(args, config: Dict[str, Any]) -> int:
    path = args.log_path or config.get("log_path")
    expected_head = read_anchor(args.anchor) if args.anchor else None
    ok, report = verify_log(path, expected_head=expected_head)

    if args.json:
        print(json.dumps({"ok": ok, "path": path, **report}, indent=2, sort_keys=True))
    elif ok:
        head = report.get("head") or {}
        print(f"OK  {path}: {report['events']} events, head {head.get('hash', '-')}")
        if expected_head is None:
            print(
                "note: without --anchor, deletion of the newest events cannot "
                "be detected"
            )
    else:
        print(f"FAILED  {path}: {report.get('error')}", file=sys.stderr)
        for key, value in sorted(report.items()):
            if key != "error":
                print(f"  {key}: {value}", file=sys.stderr)
    return 0 if ok else 1


def cmd_anchor(args, config: Dict[str, Any]) -> int:
    path = args.log_path or config.get("log_path")
    anchor = write_anchor(path, args.out)
    if anchor is None:
        raise CliError(f"{path} is empty; nothing to anchor")
    target = args.out or (path + ".anchor")
    print(json.dumps(anchor, indent=2, sort_keys=True))
    print(
        f"\nWrote {target}. Store a copy somewhere the ledger's writer cannot "
        f"reach, then verify with: llm-audit verify --anchor {target}",
        file=sys.stderr,
    )
    return 0


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------


def _add_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model-id", dest="model_id")
    parser.add_argument("--dataset-id", dest="dataset_id")
    parser.add_argument("--deployment-id", dest="deployment_id")


def _add_mode_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="prompt for every field left blank",
    )
    group.add_argument(
        "--no-interactive",
        action="store_true",
        help="never prompt; fail if a required field is missing",
    )
    parser.add_argument(
        "--reference",
        action="append",
        help="supporting URL or ticket (repeatable)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-audit",
        description="Record governance decisions and verify an audit ledger.",
    )
    parser.add_argument("--config", help="path to a config.yaml")
    parser.add_argument("--log-path", help="ledger to read or append to")
    sub = parser.add_subparsers(dest="cmd", required=True)

    approve = sub.add_parser("approve", help="record an approval")
    approve.add_argument("--owner")
    approve.add_argument("--rationale")
    approve.add_argument("--constraints", help="JSON object of deployment constraints")
    _add_scope_args(approve)
    _add_mode_args(approve)

    waive = sub.add_parser("waive", help="record a risk waiver")
    waive.add_argument("--owner")
    waive.add_argument("--rationale")
    waive.add_argument(
        "--waived-control", action="append", help="control being waived (repeatable)"
    )
    waive.add_argument("--until", help="RFC 3339 date the waiver lapses")
    _add_scope_args(waive)
    _add_mode_args(waive)

    attest = sub.add_parser("attest", help="record an attestation")
    attest.add_argument("--owner")
    attest.add_argument("--statement")
    _add_scope_args(attest)
    _add_mode_args(attest)

    verify = sub.add_parser("verify", help="verify the ledger's hash chain")
    verify.add_argument("--anchor", help="anchor file from `llm-audit anchor`")
    verify.add_argument("--json", action="store_true", help="machine-readable output")

    anchor = sub.add_parser("anchor", help="record the current chain head")
    anchor.add_argument("--out", help="where to write the anchor")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)

    try:
        if args.cmd == "verify":
            return cmd_verify(args, config)
        if args.cmd == "anchor":
            return cmd_anchor(args, config)

        handler = {"approve": cmd_approve, "waive": cmd_waive, "attest": cmd_attest}[
            args.cmd
        ]
        print(json.dumps(handler(args, config), indent=2, sort_keys=True))
        return 0
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\naborted; nothing was recorded", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
