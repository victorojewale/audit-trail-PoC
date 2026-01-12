# llm-audit-trail

**llm-audit-trail** is a lightweight Python library for emitting **tamper-evident audit events** across an LLM lifecycle and **verifying** later that the event history has not been modified or truncated.

It is designed to be used as a normal dependency: install, import, attach a callback or middleware, and you get an append-only JSONL event log you can filter for audits, compliance, or research.

---

## What this is for

An LLM audit trail is useful when you need to answer questions like:

- What dataset and configuration produced `model_id=X`?
- When did `model_id=X` get evaluated and with what metrics?
- What approvals or waivers were granted before deployment?
- What requests and responses happened in production (at metadata level), and when?
- Has the log been modified after the fact?


---


## Core ideas

### (1) Append-only events (JSONL)
Events are written to a newline-delimited JSON file by default (`audit_trail.jsonl`).

### (2) Cryptographic chaining
Each event includes a `prev_hash` and `curr_hash`. `curr_hash` is a hash of the current event content plus the prior hash, which creates a chain.
If you change, delete, or reorder a line, verification fails.

### (3) Separation by `system` and `event_type`
You can treat `system` as the “source” or “emitter” (for example `hf_trainer`, `fastapi`, `governance`), and `event_type` as the semantic event label (for example `FineTuneStart`, `Evaluation`, `InferenceRequest`, `Approval`).

---


## Install
```bash
git clone https://github.com/...../audit-trail-PoC.git
cd llm-audit-trail
pip install -e .

```

## Quick start
```python
from llm_audit_trail import AuditLogger, verify_log

log = AuditLogger(path="audit_trail.jsonl", system="demo")

log.emit("FineTuneStart", {"lr":1e-5}, model_id="demo-imdb-v1")
log.emit("Evaluation", {"accuracy":0.81}, model_id="demo-imdb-v1")

ok, report = verify_log("audit_trail.jsonl")
print("Ledger OK:", ok)
```

You should now have a file called audit_trail.jsonl containing one JSON object per line.

---

## Hugging Face integration

The library includes a Hugging Face TrainerCallback so you do not have to manually emit training lifecycle events.

```python
from llm_audit_trail import hf_audit_callback
from transformers import Trainer

cb = hf_audit_callback(model_id="demo-imdb-v1")
trainer = Trainer(..., callbacks=[cb])
trainer.train()
```

---

## FastAPI integration

FastAPI is a Python web framework used to serve APIs, often used to deploy an inference endpoint.
This library provides middleware that records request and response metadata for inference calls.

```python
from fastapi import FastAPI
from llm_audit_trail import AuditLogger, AuditMiddleware

app = FastAPI()
log = AuditLogger(path="audit_trail.jsonl", system="fastapi")

app.add_middleware(
    AuditMiddleware,
    logger=log,
    model_id="demo-imdb-v1",
    redact_previews=True,
)

@app.post("/infer")
def infer(prompt: str):
    return {"output": prompt[::-1]}

```

---

## Human-in-the-loop decisions (CLI)

The CLI is intended for governance events that should not be typed into model training code.
Interactive approvals, waivers, attestations

```bash
python -m llm_audit_trail_cli.main approve --interactive
python -m llm_audit_trail_cli.main waive --interactive
python -m llm_audit_trail_cli.main attest --interactive
```
Environment variables:
- `AUDIT_LOG_PATH`: path to the JSONL file (defaults to audit_trail.jsonl)
- `AUDIT_OWNER`: prefill the decision owner prompt


Tips:
- `AUDIT_LOG_PATH` → choose log file.  
- `AUDIT_OWNER` → prefill your name.  

---

## Dataset provenance
You can register datasets so downstream training and evaluation events can reference them.


Register Hugging Face dataset metadata
```python
from llm_audit_trail import AuditLogger
from llm_audit_trail.datasets import register_dataset

log = AuditLogger(path="audit_trail.jsonl", system="data_engineering")

register_dataset(
    log,
    dataset_id="hf:stanfordnlp/imdb",
    version="latest",
    source="huggingface://datasets/stanfordnlp/imdb",
    rows=100000,
    license="unknown",
    datasheet_url="https://huggingface.co/datasets/stanfordnlp/imdb",
    content_hash="sha256:PLACEHOLDER",
    preprocessing={"splits": ["train", "test", "unsupervised"]},
    owner="stanfordnlp",
)

```

---

## Examples
Run the included example stub:

```bash
python examples/register_and_train_stub.py
```

This will:
1. Register the IMDB dataset  
2. Emit training + evaluation events  
3. Record a governance approval  
4. Verify the ledger  


---

## Working with the log for auditing or research

Because the log is JSONL, you can filter it using `jq` or `pandas`.

### Example: show a minimal model timeline
```bash
jq -s 'sort_by(.timestamp)[] | {timestamp, system, event_type, model_id, dataset_id, deployment_id}' audit_trail.jsonl
```

### Example: all events for one model
```bash
jq 'select(.model_id=="demo-imdb-v1")' audit_trail.jsonl
```

---

## Verify integrity
```python
from llm_audit_trail import verify_log
ok, report = verify_log("audit_trail.jsonl")
print("Ledger OK:", ok)
print(report)
```

What verification catches:

- a modified event line
- a deleted event line
- reordering of lines
- truncation
---

## Roadmap
- More runnable examples (FastAPI demo, Hugging Face training flow)  
- Optional external anchoring of chain roots (signatures or append-only storage)
- Additional monitoring integrations beyond FastAPI
- Optional exporters to databases or object stores
- Stronger dataset hashing utilities for reproducible dataset snapshots
