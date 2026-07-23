"""Hugging Face ``Trainer`` integration."""

from __future__ import annotations

from typing import Optional

from transformers import TrainerCallback

from .core import AuditLogger

__all__ = ["AuditTrailCallback", "hf_audit_callback"]


class AuditTrailCallback(TrainerCallback):
    """Records the training lifecycle to an audit ledger.

    Emits ``FineTuneStart``, ``EpochEnd``, ``Evaluation``, ``Checkpoint`` and
    ``FineTuneEnd``. Metric values that arrive as numpy scalars are
    normalised during serialisation.
    """

    def __init__(
        self,
        logger: AuditLogger,
        model_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
    ) -> None:
        self.log = logger
        self.model_id = model_id
        self.dataset_id = dataset_id

    def _emit(self, event_type: str, details: dict) -> None:
        self.log.emit(
            event_type,
            details=details,
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            system="hf_trainer",
        )

    def on_train_begin(self, args, state, control, **kwargs):
        self._emit(
            "FineTuneStart",
            {
                "learning_rate": getattr(args, "learning_rate", None),
                "num_train_epochs": getattr(args, "num_train_epochs", None),
                "per_device_train_batch_size": getattr(
                    args, "per_device_train_batch_size", None
                ),
                "gradient_accumulation_steps": getattr(
                    args, "gradient_accumulation_steps", None
                ),
                "seed": getattr(args, "seed", None),
                "output_dir": getattr(args, "output_dir", None),
                "fp16": getattr(args, "fp16", False),
                "bf16": getattr(args, "bf16", False),
            },
        )

    def on_epoch_end(self, args, state, control, **kwargs):
        history = getattr(state, "log_history", None) or [{}]
        latest = history[-1] if isinstance(history, list) else {}
        epoch = getattr(state, "epoch", None)
        self._emit(
            "EpochEnd",
            {
                "epoch": float(epoch) if epoch is not None else None,
                "global_step": getattr(state, "global_step", None),
                "learning_rate": latest.get("learning_rate"),
                "loss": latest.get("loss"),
            },
        )

    def on_evaluate(self, args, state, control, metrics=None, **kwargs):
        epoch = getattr(state, "epoch", None)
        details = {"epoch": float(epoch) if epoch is not None else None}
        details.update(metrics or {})
        self._emit("Evaluation", details)

    def on_save(self, args, state, control, **kwargs):
        self._emit(
            "Checkpoint",
            {
                "global_step": getattr(state, "global_step", None),
                "output_dir": getattr(args, "output_dir", None),
            },
        )

    def on_train_end(self, args, state, control, **kwargs):
        self._emit(
            "FineTuneEnd",
            {
                "global_step": getattr(state, "global_step", None),
                "best_metric": getattr(state, "best_metric", None),
                "best_model_checkpoint": getattr(state, "best_model_checkpoint", None),
            },
        )


def hf_audit_callback(
    model_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    logger: Optional[AuditLogger] = None,
) -> AuditTrailCallback:
    """Build a callback ready to pass to ``Trainer(callbacks=[...])``."""
    return AuditTrailCallback(
        logger=logger or AuditLogger(),
        model_id=model_id,
        dataset_id=dataset_id,
    )
