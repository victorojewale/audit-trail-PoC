
# llm-audit-trail

A lightweight library to emit **tamper-evident** audit events for LLM lifecycles and to **verify** integrity later.

## Install
```bash
pip install ./llm-audit-trail-lib   # local path install
# or, once published: pip install llm-audit-trail
```

## Quick start
```python
from llm_audit_trail import AuditLogger, verify_log

log = AuditLogger(path="audit_trail.jsonl", system="demo", actor="researcher")

log.emit("FineTuneStart", {"learning_rate":1e-5, "epochs":1}, model_id="distilbert-imdb-v1")
log.emit("Evaluation", {"accuracy":0.81, "f1":0.82}, model_id="distilbert-imdb-v1")
ok, info = verify_log("audit_trail.jsonl")
print("OK" if ok else info)
```

## Hugging Face integration (optional)
```bash
pip install llm-audit-trail[hf]
```
```python
from transformers import Trainer, TrainingArguments, AutoTokenizer, AutoModelForSequenceClassification
from datasets import load_dataset
from llm_audit_trail import AuditLogger
from llm_audit_trail.hf import AuditTrailCallback

log = AuditLogger(system="hf_demo")
cb = AuditTrailCallback(logger=log, model_id="distilbert-base-uncased")

# build model/datasets as usual, then:
trainer = Trainer(model=model, args=TrainingArguments(output_dir="out", num_train_epochs=1, report_to=[]),
                  train_dataset=train_ds, eval_dataset=eval_ds, callbacks=[cb])
trainer.train()
trainer.evaluate()
```

## FastAPI middleware (optional)
```bash
pip install llm-audit-trail[fastapi] uvicorn
```
```python
from fastapi import FastAPI
from llm_audit_trail import AuditLogger
from llm_audit_trail.fastapi import AuditMiddleware

app = FastAPI()
log = AuditLogger(system="api")
app.add_middleware(AuditMiddleware, logger=log, redact_previews=True)

@app.post("/infer")
def infer(prompt: str):
    return {"output": prompt[::-1]}
```

## Verify integrity



## Decisions: three human-authored event types


## Interactive human-in-the-loop CLI

You can record approvals, waivers, and attestations without flags. The CLI will prompt for the fields and suggest recent IDs from your audit log.

```bash
python -m llm_audit_trail_cli.main approve --interactive
python -m llm_audit_trail_cli.main waive --interactive
python -m llm_audit_trail_cli.main attest --interactive
```

Tips:
- Set `AUDIT_LOG_PATH` to choose a log file.
- Set `AUDIT_OWNER` to prefill the owner prompt.
- The prompt suggests recent `model_id`, `dataset_id`, `deployment_id` seen in the last ~50 events.
- JSON prompts accept inline JSON; press Enter to accept defaults.


## Dataset provenance helpers

