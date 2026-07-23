"""End-to-end walkthrough: provenance, training, approval, verification.

Runs on the core install alone — no transformers, no HF datasets, no network:

    python examples/register_and_train_stub.py

Set AUDIT_HMAC_KEY first to see the keyed variant of the chain.
"""

from __future__ import annotations

import os
import tempfile

from llm_audit_trail import (
    AuditLogger,
    record_approval,
    register_dataset,
    verify_log,
    write_anchor,
)

MODEL_ID = "demo-imdb-v1"
DATASET_ID = "hf:stanfordnlp/imdb"


def main() -> None:
    path = os.path.join(tempfile.mkdtemp(prefix="llm-audit-"), "audit_trail.jsonl")
    log = AuditLogger(path=path, system="demo")

    # 1) Where the data came from. content_hash should be a real digest of the
    #    snapshot you trained on; a placeholder here keeps the example offline.
    register_dataset(
        log,
        dataset_id=DATASET_ID,
        version="latest",
        source="huggingface://datasets/stanfordnlp/imdb",
        rows=100_000,
        license="unknown",
        datasheet_url="https://huggingface.co/datasets/stanfordnlp/imdb",
        content_hash="sha256:PLACEHOLDER",
        preprocessing={"splits": ["train", "test", "unsupervised"]},
        owner="stanfordnlp",
    )

    # 2) Training. The hf extra emits these automatically via AuditTrailCallback.
    log.emit(
        "FineTuneStart",
        {"learning_rate": 1e-5, "num_train_epochs": 1, "code_commit": "abc123"},
        model_id=MODEL_ID,
        dataset_id=DATASET_ID,
        system="hf_trainer",
    )
    log.emit(
        "Evaluation",
        {"accuracy": 0.88, "f1": 0.87},
        model_id=MODEL_ID,
        dataset_id=DATASET_ID,
        system="hf_trainer",
    )

    # 3) A human takes responsibility for shipping it.
    record_approval(
        log,
        owner="Model Risk Committee",
        rationale="Accuracy and F1 clear the launch thresholds",
        scope={
            "model_id": MODEL_ID,
            "dataset_id": DATASET_ID,
            "deployment_id": "prod-1",
        },
        constraints={"rollout": "10% for 48h"},
    )

    # 4) Verify, then anchor so later truncation is detectable.
    ok, report = verify_log(path)
    anchor = write_anchor(path)

    print(f"ledger:   {path}")
    print(f"verified: {ok} ({report['events']} events)")
    print(f"head:     seq {anchor['seq']} {anchor['hash'][:16]}...")
    print(f"anchor:   {path}.anchor")
    print(
        "\nStore that anchor outside this machine, then re-check with:\n"
        f"  llm-audit --log-path {path} verify --anchor {path}.anchor"
    )


if __name__ == "__main__":
    main()
