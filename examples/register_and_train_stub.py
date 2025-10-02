# examples/register_and_train_stub.py


from datasets import load_dataset
from llm_audit_trail import AuditLogger, verify_log
from llm_audit_trail.datasets import register_dataset
from llm_audit_trail.decisions import record_approval

# Load IMDB dataset from Hugging Face
ds = load_dataset("stanfordnlp/imdb")
num_rows = sum(len(ds[split]) for split in ds)

log = AuditLogger()

# 1) Register dataset
register_dataset(
    log,
    dataset_id="hf:stanfordnlp/imdb",
    version="latest",
    source="huggingface://datasets/stanfordnlp/imdb",
    rows=num_rows,
    license=ds.info.license if hasattr(ds, "info") and ds.info.license else "unknown",
    datasheet_url="https://huggingface.co/datasets/stanfordnlp/imdb",
    content_hash="sha256:PLACEHOLDER",
    preprocessing={"splits": list(ds.keys())},
    owner="stanfordnlp"
)

# 2) Emit FineTuneStart
log.emit(
    "FineTuneStart",
    details={"learning_rate":1e-5,"num_train_epochs":1,"code_commit":"abc123"},
    model_id="demo-imdb-v1",
    dataset_id="hf:stanfordnlp/imdb",
    system="hf_trainer"
)

# 3) Simulate evaluation
log.emit(
    "Evaluation",
    details={"accuracy":0.88,"f1":0.87},
    model_id="demo-imdb-v1",
    dataset_id="hf:stanfordnlp/imdb",
    system="hf_trainer"
)

# 4) Human approval
record_approval(
    log,
    owner="Model Risk Committee",
    rationale="Meets thresholds",
    scope={"model_id":"demo-imdb-v1","dataset_id":"hf:stanfordnlp/imdb","deployment_id":"prod-1"}
)

# 5) Verify the log
ok, report = verify_log("audit_trail.jsonl")
print("Ledger OK:", ok)
print(report)
