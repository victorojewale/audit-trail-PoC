from __future__ import annotations
from typing import Optional
from transformers import TrainerCallback
from .core import AuditLogger

class AuditTrailCallback(TrainerCallback):
    """Hugging Face Trainer callback that auto-logs training lifecycle."""
    def __init__(self, logger: AuditLogger, model_id: Optional[str] = None, dataset_id: Optional[str] = None):
        self.log = logger
        self.model_id = model_id
        self.dataset_id = dataset_id

    def on_train_begin(self, args, state, control, **kwargs):
        self.log.emit(
            "FineTuneStart",
            details={
                "learning_rate": getattr(args, "learning_rate", None),
                "num_train_epochs": getattr(args, "num_train_epochs", None),
                "per_device_train_batch_size": getattr(args, "per_device_train_batch_size", None),
                "gradient_accumulation_steps": getattr(args, "gradient_accumulation_steps", None),
                "seed": getattr(args, "seed", None),
                "output_dir": getattr(args, "output_dir", None),
                "fp16": getattr(args, "fp16", False),
            },
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            system="hf_trainer",
        )

    def on_epoch_end(self, args, state, control, **kwargs):
        hist = getattr(state, "log_history", []) or [{}]
        last = hist[-1] if isinstance(hist, list) else {}
        self.log.emit(
            "EpochEnd",
            details={
                "epoch": float(state.epoch) if state.epoch is not None else None,
                "global_step": getattr(state, "global_step", None),
                "learning_rate": last.get("learning_rate"),
                "loss": last.get("loss"),
            },
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            system="hf_trainer",
        )

    def on_evaluate(self, args, state, control, metrics, **kwargs):
        det = {"epoch": float(state.epoch) if state.epoch is not None else None}
        det.update(metrics or {})
        self.log.emit(
            "Evaluation",
            details=det,
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            system="hf_trainer",
        )

    def on_save(self, args, state, control, **kwargs):
        self.log.emit(
            "Checkpoint",
            details={"global_step": getattr(state, "global_step", None),
                     "output_dir": getattr(args, "output_dir", None)},
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            system="hf_trainer",
        )

    def on_train_end(self, args, state, control, **kwargs):
        self.log.emit(
            "FineTuneEnd",
            details={
                "global_step": getattr(state, "global_step", None),
                "best_metric": getattr(state, "best_metric", None),
                "best_model_checkpoint": getattr(state, "best_model_checkpoint", None),
            },
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            system="hf_trainer",
        )

def hf_audit_callback(
    model_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    logger: Optional[AuditLogger] = None
) -> AuditTrailCallback:
    """Convenience factory so users can pass this straight to Trainer(callbacks=[...])."""
    logger = logger or AuditLogger()
    return AuditTrailCallback(logger=logger, model_id=model_id, dataset_id=dataset_id)
