"""What verification detects — and, just as importantly, what it does not."""

from __future__ import annotations

import hashlib
import json

from llm_audit_trail import AuditLogger, read_head, verify_log, write_anchor
from llm_audit_trail.core import GENESIS, _stable_json


def _seed(path, count=5, **kwargs):
    log = AuditLogger(path=str(path), **kwargs)
    for i in range(count):
        log.emit("E", {"i": i}, model_id="m1")
    return log


def _lines(path):
    return path.read_text().splitlines(keepends=True)


def _rewrite(path, records):
    path.write_text("".join(_stable_json(r) + "\n" for r in records))


def _rechain(records, key=None):
    """Recompute every hash, as an attacker with write access would."""
    previous = GENESIS
    for record in records:
        record.pop("curr_hash", None)
        record["prev_hash"] = previous
        payload = (previous + _stable_json(record)).encode("utf-8")
        if key:
            import hmac

            record["curr_hash"] = hmac.new(key, payload, hashlib.sha256).hexdigest()
        else:
            record["curr_hash"] = hashlib.sha256(payload).hexdigest()
        previous = record["curr_hash"]
    return records


# --------------------------------------------------------------------------
# detected
# --------------------------------------------------------------------------


def test_edited_event_is_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path)

    records = [json.loads(line) for line in _lines(path)]
    records[2]["details"]["i"] = 999
    _rewrite(path, records)

    ok, report = verify_log(str(path))
    assert not ok
    assert report["error"] == "hash_mismatch"
    assert report["line"] == 3


def test_deleted_event_is_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path)

    lines = _lines(path)
    path.write_text("".join(lines[:2] + lines[3:]))

    ok, report = verify_log(str(path))
    assert not ok
    assert report["error"] == "broken_link"


def test_reordered_events_are_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path)

    lines = _lines(path)
    lines[1], lines[2] = lines[2], lines[1]
    path.write_text("".join(lines))

    ok, report = verify_log(str(path))
    assert not ok
    assert report["error"] in {"broken_link", "hash_mismatch"}


def test_blank_lines_are_tolerated(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path, count=2)
    path.write_text(path.read_text() + "\n\n")

    ok, report = verify_log(str(path))
    assert ok
    assert report["events"] == 2


def test_missing_file_reports_instead_of_raising(tmp_path):
    ok, report = verify_log(str(tmp_path / "nope.jsonl"))
    assert not ok
    assert report["error"] == "unreadable"


def test_malformed_json_reports_instead_of_raising(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path, count=1)
    path.write_text(path.read_text() + "{not json}\n")

    ok, report = verify_log(str(path))
    assert not ok
    assert report["error"] == "malformed_json"
    assert report["line"] == 2


def test_record_without_hash_reports_instead_of_raising(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text(json.dumps({"event_type": "E"}) + "\n")

    ok, report = verify_log(str(path))
    assert not ok
    assert report["error"] == "missing_curr_hash"


def test_empty_ledger_verifies_with_no_head(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text("")
    ok, report = verify_log(str(path))
    assert ok
    assert report == {"events": 0, "head": None}


# --------------------------------------------------------------------------
# tail truncation: invisible alone, caught with an anchor
# --------------------------------------------------------------------------


def test_truncation_is_invisible_without_an_anchor(tmp_path):
    """Documents the limit of a self-contained chain."""
    path = tmp_path / "audit.jsonl"
    _seed(path, count=5)

    path.write_text("".join(_lines(path)[:2]))

    ok, _ = verify_log(str(path))
    assert ok, "a bare hash chain cannot see events removed from the end"


def test_anchor_detects_truncation(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path, count=5)
    anchor = write_anchor(str(path))
    assert anchor["seq"] == 4

    path.write_text("".join(_lines(path)[:2]))

    ok, report = verify_log(str(path), expected_head=anchor)
    assert not ok
    assert report["error"] == "anchor_missing"


def test_anchor_allows_the_ledger_to_keep_growing(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed(path, count=3)
    anchor = write_anchor(str(path))

    log.emit("E", {"i": "later"})

    ok, report = verify_log(str(path), expected_head=anchor)
    assert ok, report
    assert report["events"] == 4


def test_anchor_detects_a_rewritten_anchored_event(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path, count=3)
    anchor = write_anchor(str(path))

    records = _rechain([json.loads(line) for line in _lines(path)])
    records[2]["details"]["i"] = "tampered"
    _rewrite(path, _rechain(records))

    ok, report = verify_log(str(path), expected_head=anchor)
    assert not ok
    assert report["error"] == "anchor_mismatch"


def test_read_head_matches_the_last_event(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed(path, count=3)
    last = log.emit("E", {"i": "final"})

    head = read_head(str(path))
    assert head["hash"] == last["curr_hash"]
    assert head["seq"] == last["seq"]
    assert read_head(str(tmp_path / "absent.jsonl")) is None


# --------------------------------------------------------------------------
# keyed chains
# --------------------------------------------------------------------------


def test_unkeyed_chain_can_be_forged(tmp_path):
    """The reason `key=` exists: SHA-256 alone only proves nothing broke."""
    path = tmp_path / "audit.jsonl"
    _seed(path, count=3)

    records = [json.loads(line) for line in _lines(path)]
    records[1]["details"]["i"] = "forged"
    _rewrite(path, _rechain(records))

    ok, _ = verify_log(str(path))
    assert ok, "an unkeyed chain is recomputable by anyone with write access"


def test_keyed_chain_resists_forgery(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path, count=3, key="s3cret")

    records = [json.loads(line) for line in _lines(path)]
    records[1]["details"]["i"] = "forged"
    _rewrite(path, _rechain(records, key=b"wrong-key"))

    ok, report = verify_log(str(path), key="s3cret")
    assert not ok
    assert report["error"] == "hash_mismatch"


def test_keyed_chain_verifies_with_the_right_key(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path, count=3, key="s3cret")

    ok, report = verify_log(str(path), key="s3cret")
    assert ok, report
    assert report["events"] == 3


def test_keyed_chain_reports_a_missing_key(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path, count=2, key="s3cret")

    ok, report = verify_log(str(path))
    assert not ok
    assert report["error"] == "key_required"


def test_key_can_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_HMAC_KEY", "from-env")
    path = tmp_path / "audit.jsonl"
    _seed(path, count=2)

    assert json.loads(_lines(path)[0])["hash_alg"] == "hmac-sha256"
    ok, _ = verify_log(str(path))
    assert ok

    monkeypatch.delenv("AUDIT_HMAC_KEY")
    ok, report = verify_log(str(path))
    assert not ok
    assert report["error"] == "key_required"


def test_logger_verify_helper_reuses_its_own_key(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed(path, count=2, key="s3cret")
    ok, report = log.verify()
    assert ok, report
