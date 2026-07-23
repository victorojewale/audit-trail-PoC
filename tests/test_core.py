"""Chain construction, locking and serialisation."""

from __future__ import annotations

import json
import subprocess
import sys
import threading

import pytest

from llm_audit_trail import AuditLogError, AuditLogger, iter_events, verify_log
from llm_audit_trail.core import GENESIS


def test_emit_builds_a_verifiable_chain(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLogger(path=path, system="demo")

    log.emit("FineTuneStart", {"lr": 1e-5}, model_id="demo-v1")
    log.emit("Evaluation", {"accuracy": 0.81}, model_id="demo-v1")

    ok, report = verify_log(path)
    assert ok, report
    assert report["events"] == 2


def test_first_event_links_to_genesis(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    event = AuditLogger(path=path).emit("Start", {})
    assert event["prev_hash"] == GENESIS
    assert event["seq"] == 0


def test_sequence_numbers_are_monotonic(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLogger(path=path)
    events = [log.emit("E", {"i": i}) for i in range(5)]
    assert [e["seq"] for e in events] == [0, 1, 2, 3, 4]


def test_timestamps_distinguish_events_in_the_same_second(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLogger(path=path)
    stamps = [log.emit("E", {"i": i})["timestamp"] for i in range(3)]
    assert len(set(stamps)) == 3, "sub-second resolution lost"
    assert all(stamp.endswith("Z") and "." in stamp for stamp in stamps)


def test_parent_directories_are_created(tmp_path):
    path = str(tmp_path / "nested" / "deeper" / "audit.jsonl")
    AuditLogger(path=path).emit("E", {})
    ok, _ = verify_log(path)
    assert ok


def test_details_default_to_an_empty_object(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    assert AuditLogger(path=path).emit("Ping")["details"] == {}


class _NumpyLike:
    """Stands in for a numpy scalar, which json cannot encode natively."""

    def __init__(self, value):
        self._value = value

    def item(self):
        return self._value


def test_non_json_values_are_coerced_rather_than_crashing(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLogger(path=path)
    log.emit("Evaluation", {"accuracy": _NumpyLike(0.88), "note": object()})

    ok, _ = verify_log(path)
    assert ok
    details = next(iter_events(path))["details"]
    assert details["accuracy"] == 0.88
    assert isinstance(details["note"], str)


# --------------------------------------------------------------------------
# concurrency
# --------------------------------------------------------------------------


def test_concurrent_threads_keep_the_chain_intact(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLogger(path=path, system="load")

    def worker(worker_id):
        for i in range(25):
            log.emit("E", {"worker": worker_id, "i": i})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    ok, report = verify_log(path)
    assert ok, report
    assert report["events"] == 200


def test_separate_logger_instances_do_not_race(tmp_path):
    path = str(tmp_path / "audit.jsonl")

    def worker(worker_id):
        # a fresh logger per thread: only the file lock can serialise these
        own_log = AuditLogger(path=path)
        for i in range(20):
            own_log.emit("E", {"worker": worker_id, "i": i})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    ok, report = verify_log(path)
    assert ok, report
    assert report["events"] == 120


_CHILD = """
import sys
from llm_audit_trail import AuditLogger
log = AuditLogger(path=sys.argv[1])
for i in range(30):
    log.emit("E", {"pid": sys.argv[2], "i": i})
"""


def test_concurrent_processes_keep_the_chain_intact(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    script = tmp_path / "child.py"
    script.write_text(_CHILD)

    children = [
        subprocess.Popen([sys.executable, str(script), path, str(n)]) for n in range(4)
    ]
    for child in children:
        assert child.wait(timeout=120) == 0

    ok, report = verify_log(path)
    assert ok, report
    assert report["events"] == 120


# --------------------------------------------------------------------------
# corrupt ledgers
# --------------------------------------------------------------------------


def test_appending_to_a_corrupt_tail_is_refused(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLogger(path=str(path))
    log.emit("E", {})
    path.write_text(path.read_text() + '{"partial": tru\n')

    # silently restarting the chain would hide the damage
    with pytest.raises(AuditLogError, match="corrupt ledger"):
        log.emit("E", {})


def test_tail_without_a_hash_is_refused(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text(json.dumps({"event_type": "E"}) + "\n")

    with pytest.raises(AuditLogError, match="curr_hash"):
        AuditLogger(path=str(path)).emit("E", {})


def test_trailing_newlines_do_not_break_appends(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLogger(path=str(path))
    log.emit("E", {"i": 0})
    path.write_text(path.read_text() + "\n\n")
    log.emit("E", {"i": 1})

    ok, report = verify_log(str(path))
    assert ok, report
    assert report["events"] == 2
