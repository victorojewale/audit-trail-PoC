"""The CLI must work from flags, not only from a human at a terminal."""

from __future__ import annotations

import json
import os

import pytest

from llm_audit_trail import iter_events, verify_log
from llm_audit_trail_cli.main import main


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    # keep the CLI away from any real ~/.llm-audit or /etc/llm-audit
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AUDIT_OWNER", raising=False)
    monkeypatch.delenv("AUDIT_LOG_PATH", raising=False)
    monkeypatch.setattr("llm_audit_trail.config.SEARCH_PATHS", [])
    monkeypatch.setattr("llm_audit_trail_cli.main.load_decision_spec", lambda e, c: {"fields": {}})
    return str(tmp_path / "audit.jsonl")


def test_approve_from_flags(ledger, capsys):
    code = main(
        [
            "--log-path", ledger,
            "approve",
            "--owner", "Model Risk Committee",
            "--rationale", "meets thresholds",
            "--model-id", "demo-v1",
            "--constraints", '{"rollout": "10% for 48h"}',
            "--reference", "https://tickets/AUD-1",
            "--no-interactive",
        ]
    )
    assert code == 0

    event = json.loads(capsys.readouterr().out)
    assert event["event_type"] == "Approval"
    assert event["details"]["constraints"] == {"rollout": "10% for 48h"}
    assert event["details"]["references"] == ["https://tickets/AUD-1"]
    assert event["model_id"] == "demo-v1"

    ok, _ = verify_log(ledger)
    assert ok


def test_waive_from_flags(ledger, capsys):
    code = main(
        [
            "--log-path", ledger,
            "waive",
            "--owner", "MRC",
            "--rationale", "pilot exception",
            "--waived-control", "SLO:latency_p95",
            "--waived-control", "eval:toxicity",
            "--until", "2026-12-31",
            "--no-interactive",
        ]
    )
    assert code == 0
    event = json.loads(capsys.readouterr().out)
    assert event["details"]["waived_controls"] == ["SLO:latency_p95", "eval:toxicity"]
    assert event["details"]["time_bound_until"] == "2026-12-31"


def test_attest_from_flags(ledger, capsys):
    code = main(
        [
            "--log-path", ledger,
            "attest",
            "--owner", "Compliance",
            "--statement", "data licensed and in scope",
            "--dataset-id", "hf:imdb",
            "--no-interactive",
        ]
    )
    assert code == 0
    event = json.loads(capsys.readouterr().out)
    assert event["event_type"] == "Attestation"
    assert event["dataset_id"] == "hf:imdb"


def test_missing_required_field_fails_loudly(ledger, capsys):
    code = main(["--log-path", ledger, "approve", "--owner", "MRC", "--no-interactive"])

    assert code == 2
    assert "rationale" in capsys.readouterr().err
    # a half-specified decision must not reach the ledger at all
    assert not os.path.exists(ledger) or list(iter_events(ledger)) == []


def test_missing_owner_is_not_silently_invented(ledger, capsys):
    code = main(
        ["--log-path", ledger, "approve", "--rationale", "fine", "--no-interactive"]
    )
    assert code == 2
    assert "owner" in capsys.readouterr().err


def test_verify_reports_success(ledger, capsys):
    main(
        ["--log-path", ledger, "approve", "--owner", "MRC",
         "--rationale", "ok", "--no-interactive"]
    )
    capsys.readouterr()

    assert main(["--log-path", ledger, "verify"]) == 0
    assert "OK" in capsys.readouterr().out


def test_verify_exits_nonzero_on_tampering(ledger, capsys):
    main(
        ["--log-path", ledger, "approve", "--owner", "MRC",
         "--rationale", "ok", "--no-interactive"]
    )
    capsys.readouterr()

    with open(ledger, "r+", encoding="utf-8") as fh:
        record = json.loads(fh.read())
        record["details"]["rationale"] = "tampered"
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(record) + "\n")

    assert main(["--log-path", ledger, "verify"]) == 1
    assert "FAILED" in capsys.readouterr().err


def test_verify_json_output(ledger, capsys):
    main(
        ["--log-path", ledger, "attest", "--owner", "C",
         "--statement", "s", "--no-interactive"]
    )
    capsys.readouterr()

    main(["--log-path", ledger, "verify", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["events"] == 1


def test_anchor_then_detect_truncation(ledger, capsys, tmp_path):
    for i in range(3):
        main(
            ["--log-path", ledger, "attest", "--owner", "C",
             "--statement", f"s{i}", "--no-interactive"]
        )
    capsys.readouterr()

    anchor = str(tmp_path / "head.json")
    assert main(["--log-path", ledger, "anchor", "--out", anchor]) == 0
    capsys.readouterr()

    with open(ledger, "r", encoding="utf-8") as fh:
        kept = fh.readlines()[:1]
    with open(ledger, "w", encoding="utf-8") as fh:
        fh.writelines(kept)

    # unanchored verification cannot see the loss; anchored verification can
    assert main(["--log-path", ledger, "verify"]) == 0
    capsys.readouterr()
    assert main(["--log-path", ledger, "verify", "--anchor", anchor]) == 1
    assert "anchor_missing" in capsys.readouterr().err


def test_anchor_on_empty_ledger_errors(ledger, capsys):
    open(ledger, "w").close()
    assert main(["--log-path", ledger, "anchor"]) == 2
    assert "nothing to anchor" in capsys.readouterr().err
