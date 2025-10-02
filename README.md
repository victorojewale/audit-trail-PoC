# llm-audit-trail

**llm-audit-trail** is a lightweight library to emit **tamper-evident audit events** for LLM lifecycles and to **verify** integrity later.  
It supports logging training, evaluation, deployment, dataset provenance, and human-in-the-loop governance decisions.

---

## Features
- **Event logging** – record lifecycle events with cryptographic chaining.  
- **Verification** – detect tampering or missing entries.  
- **Integrations** – Hugging Face `Trainer` callback, FastAPI middleware.  
- **Dataset provenance** – register datasets with metadata and checksums.  
- **Human-in-the-loop** – approvals, waivers, attestations via CLI.  

---
## Install
```bash
git clone https://github.com/victorojewale/audit-trail-PoC.git
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

---

## Hugging Face integration
```python
from llm_audit_trail import hf_audit_callback
from transformers import Trainer

cb = hf_audit_callback(model_id="demo-imdb-v1")
trainer = Trainer(..., callbacks=[cb])
trainer.train()
```

---

## FastAPI integration
```python
from fastapi import FastAPI
from llm_audit_trail import AuditLogger, AuditMiddleware

app = FastAPI()
log = AuditLogger(system="api")
app.add_middleware(AuditMiddleware, logger=log, model_id="demo-imdb-v1")
```

---

## Human-in-the-loop decisions (CLI)

Interactive CLI for governance events:

```bash
python -m llm_audit_trail_cli.main approve --interactive
python -m llm_audit_trail_cli.main waive --interactive
python -m llm_audit_trail_cli.main attest --interactive
```

Tips:
- `AUDIT_LOG_PATH` → choose log file.  
- `AUDIT_OWNER` → prefill your name.  

---

## Dataset provenance
```python
from llm_audit_trail.datasets import register_dataset
from llm_audit_trail import AuditLogger

log = AuditLogger()
register_dataset(
    log,
    dataset_id="hf:stanfordnlp/imdb",
    version="latest",
    source="huggingface://datasets/stanfordnlp/imdb",
    rows=50000,
    license="unknown",
    datasheet_url="https://huggingface.co/datasets/stanfordnlp/imdb",
    content_hash="sha256:PLACEHOLDER",
    preprocessing={"splits": ["train", "test"]},
    owner="Data Eng"
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

## Verify integrity
```python
from llm_audit_trail import verify_log
ok, report = verify_log("audit_trail.jsonl")
print("Ledger OK:", ok)
print(report)
```

---

## Roadmap
- More runnable examples (FastAPI demo, Hugging Face training flow)  
- Optional sinks (e.g. W&B, S3, databases)  
- Richer dataset provenance helpers  
