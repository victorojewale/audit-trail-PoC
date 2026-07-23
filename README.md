# llm-audit-trail

[![PyPI version](https://img.shields.io/pypi/v/llm-audit-trail.svg)](https://pypi.org/project/llm-audit-trail/)
[![Python versions](https://img.shields.io/pypi/pyversions/llm-audit-trail.svg)](https://pypi.org/project/llm-audit-trail/)
[![License](https://img.shields.io/pypi/l/llm-audit-trail.svg)](https://github.com/victorojewale/audit-trail-PoC/blob/main/LICENSE)
[![CI](https://github.com/victorojewale/audit-trail-PoC/actions/workflows/ci.yml/badge.svg)](https://github.com/victorojewale/audit-trail-PoC/actions/workflows/ci.yml)

**Tamper-evident audit trails for the LLM lifecycle — training, approval, deployment, and serving.**

`llm-audit-trail` records what happened to a model as an append-only, hash-chained event log: which dataset trained it, how it scored, who approved its release and on what grounds, and what it served in production. Each event is cryptographically linked to the one before it, so an edit, deletion, or reordering after the fact is detectable rather than invisible.

It exists because *"we have logs"* and *"we can show our logs weren't altered"* are different claims. Audits, incident reviews, and model-governance frameworks increasingly ask for the second, and an ordinary log file cannot support it.

## Features

- **Append-only JSONL** — one event per line, readable with `jq`, `pandas`, or any text tool. No service, database, or network.
- **Hash-chained** — every event commits to the previous one; edits, deletions, reordering, insertions, and corruption are all caught by `verify_log`.
- **Concurrency-safe** — appends take an exclusive file lock, so threads, uvicorn workers, and separate processes can share one ledger without forking the chain.
- **Optional HMAC keying** — makes the chain unforgeable by anyone who doesn't hold the key.
- **Anchoring** — detects deletion of the newest events, which no self-contained chain can see on its own.
- **Built-in integrations** — Hugging Face `Trainer` callback, FastAPI middleware, and a CLI for human sign-off.
- **Light** — one runtime dependency (PyYAML); integrations are optional extras.

> **Status:** alpha. The event schema and API may change before 1.0.

## Install

```bash
pip install llm-audit-trail
```

Requires Python 3.9+.

## Quick start

```python
from llm_audit_trail import AuditLogger, verify_log

log = AuditLogger(path="audit_trail.jsonl", system="demo")
log.emit("FineTuneStart", {"lr": 1e-5}, model_id="demo-imdb-v1")
log.emit("Evaluation", {"accuracy": 0.81}, model_id="demo-imdb-v1")

ok, report = verify_log("audit_trail.jsonl")   # True {'events': 2, 'head': {...}}
```

Each event carries `prev_hash` and `curr_hash`, where `curr_hash` covers the event's contents plus the previous hash.

## Integrity

`verify_log` catches edits, deletions, reordering, insertions, and corruption anywhere in the log. It never raises — it returns `(ok, report)`, where a failing report carries an error code (`hash_mismatch`, `broken_link`, `seq_gap`, `anchor_missing`, `malformed_json`, `unreadable`, `key_required`) and the offending line number.

Two things a self-contained hash chain cannot do alone, each with a fix.

**Key the chain.** An unkeyed SHA-256 chain can be recomputed by anyone who can write the file, so verification proves the log is *internally consistent*, not *authentic*. A secret makes it HMAC-SHA256:

```python
log = AuditLogger(path="audit_trail.jsonl", key="…")   # or set AUDIT_HMAC_KEY
ok, report = verify_log("audit_trail.jsonl", key="…")
```

Keep the key off the machine that writes the ledger.

**Anchor the head.** Nothing inside a log can prove events once existed past its last line, so deletions from the end are invisible. Record the head somewhere the writer can't reach — another host, an append-only bucket, a signed commit — and pass it back:

```python
from llm_audit_trail import write_anchor, read_anchor

anchor = write_anchor("audit_trail.jsonl")           # -> audit_trail.jsonl.anchor
ok, report = verify_log("audit_trail.jsonl",
                        expected_head=read_anchor("audit_trail.jsonl.anchor"))
```

The ledger may grow past the anchor; it may not lose it.

## Integrations

**Hugging Face** (`pip install 'llm-audit-trail[hf]'`) — emits `FineTuneStart`, `EpochEnd`, `Evaluation`, `Checkpoint`, `FineTuneEnd`. Numpy metrics are normalised automatically.

```python
from llm_audit_trail import hf_audit_callback
trainer = Trainer(..., callbacks=[hf_audit_callback(model_id="demo-imdb-v1")])
```

**FastAPI** (`pip install 'llm-audit-trail[fastapi]'`) — logs request/response metadata, correlated by `request_id`. Ledger writes run off the event loop.

```python
from llm_audit_trail import AuditLogger, AuditMiddleware

app.add_middleware(
    AuditMiddleware,
    logger=AuditLogger(path="audit_trail.jsonl", system="fastapi"),
    model_id="demo-imdb-v1",
    redact_previews=True,    # default: store body hashes, never body text
    log_client_ip=False,     # default: an IP is personal data, and this log is append-only
)
```

For streaming endpoints pass `buffer_response=False`; the response is passed straight through and `resp_hash` is `None`.

**Dataset provenance**

```python
from llm_audit_trail import register_dataset

register_dataset(log, dataset_id="hf:stanfordnlp/imdb", version="latest",
                 source="huggingface://datasets/stanfordnlp/imdb", rows=100000,
                 content_hash="sha256:…",    # digest the snapshot you actually trained on
                 preprocessing={"splits": ["train", "test"]}, owner="stanfordnlp")
```

JSON Schemas for governance and dataset event `details` ship with the package — see `llm_audit_trail.registry.load_schema`.

## CLI

Governance decisions belong to people, not training scripts. `llm-audit` works interactively and from flags, so the same tool serves a human and a CI job.

```bash
llm-audit approve --interactive          # prompts for anything blank, offers recent IDs

llm-audit approve --owner "Model Risk Committee" --rationale "clears thresholds" \
                  --model-id demo-imdb-v1 --constraints '{"rollout": "10% for 48h"}'
llm-audit waive   --owner MRC --rationale "pilot" --waived-control SLO:latency_p95
llm-audit attest  --owner Compliance --statement "Data licensed and in scope"

llm-audit anchor --out /secure/head.json
llm-audit verify --anchor /secure/head.json     # exit 0 = intact, 1 = failed
```

Required fields are never invented: a decision missing an owner or rationale is rejected, not recorded with a placeholder.

Environment: `AUDIT_LOG_PATH`, `AUDIT_OWNER`, `AUDIT_HMAC_KEY`. Config layers from `/etc/llm-audit/`, `~/.llm-audit/`, `./.llm-audit/`, then `--config`, then the environment. Prompt fields are customisable in `.llm-audit/decisions.yaml`.

## Event shape

```json
{
  "schema_version": "0.2.0",
  "seq": 0,
  "event_id": "…uuid4…",
  "timestamp": "2026-01-02T09:15:04.123456Z",
  "event_type": "Evaluation",
  "actor": null,
  "system": "hf_trainer",
  "model_id": "demo-imdb-v1",
  "dataset_id": "hf:stanfordnlp/imdb",
  "deployment_id": null,
  "details": {"accuracy": 0.88},
  "hash_alg": "sha256",
  "prev_hash": "GENESIS",
  "curr_hash": "…"
}
```

`seq` is gap-checked and timestamps carry microseconds, so events written in the same second stay ordered. Read them back with `iter_events(path)`, or:

```bash
jq 'select(.model_id=="demo-imdb-v1")' audit_trail.jsonl
```

## Contributing

```bash
git clone https://github.com/victorojewale/audit-trail-PoC.git
cd audit-trail-PoC
pip install -e '.[dev]'
pytest
```

Run `python examples/register_and_train_stub.py` for an offline end-to-end walkthrough. Issues and pull requests are welcome at [audit-trail-PoC](https://github.com/victorojewale/audit-trail-PoC).

## License

[Apache-2.0](https://github.com/victorojewale/audit-trail-PoC/blob/main/LICENSE)
