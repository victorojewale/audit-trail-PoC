
from llm_audit_trail import AuditLogger, verify_log
from llm_audit_trail.datasets import register_dataset
from llm_audit_trail.decisions import record_approval

log = AuditLogger()

# 1) Register dataset
register_dataset(
    log,
    dataset_id="cust-support-2025-09",
    version="2025-09-30",
    source="s3://org-datalake/datasets/cust-support/2025-09/",
    rows=50000,
    license="internal",
    datasheet_url="https://example.org/datasheets/cust-support-2025-09",
    content_hash="sha256:deadbeefcafefeed...",      # replace with real hash
    preprocessing={"pii_scrub":"v1.3","lang":["en"],"dedupe":True},
    owner="Data Eng",
)

# 2) Emit a FineTuneStart that links the dataset and model
log.emit(
    "FineTuneStart",
    details={"learning_rate":1e-5,"num_train_epochs":1,"code_commit":"abc123"},
    model_id="distilbert-imdb-v1",
    dataset_id="cust-support-2025-09",
    system="hf_trainer"
)

# 3) Simulate evaluation
log.emit(
    "Evaluation",
    details={"accuracy":0.81,"f1":0.82},
    model_id="distilbert-imdb-v1",
    dataset_id="cust-support-2025-09",
    system="hf_trainer"
)

# 4) Human approval (non-interactive example)
record_approval(
    log,
    owner="Model Risk Committee",
    rationale="Meets thresholds",
    scope={"model_id":"distilbert-imdb-v1","deployment_id":"prod-a"}
)

# 5) Verify the chain
print("Ledger OK:", verify_log("audit_trail.jsonl"))
