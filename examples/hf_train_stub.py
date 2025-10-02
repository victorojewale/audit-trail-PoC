
# examples/hf_train_stub.py
# Minimal demo that does not require torch; it simulates callback hooks.
from llm_audit_trail import AuditLogger
from llm_audit_trail.hf import AuditTrailCallback

log = AuditLogger(system="hf_stub")
cb = AuditTrailCallback(logger=log, model_id="distilbert-imdb-poc")

class A: pass
args = A(); args.learning_rate=1e-5; args.num_train_epochs=1; args.per_device_train_batch_size=8; args.gradient_accumulation_steps=1; args.seed=42; args.output_dir="out"; args.fp16=False
state = A(); state.epoch=0; state.global_step=0; state.log_history=[]
cb.on_train_begin(args=args, state=state, control=None)
state.epoch=1.0; state.global_step=100; state.log_history=[{"epoch":1,"learning_rate":1e-5,"loss":0.5}]
cb.on_epoch_end(args=args, state=state, control=None)
cb.on_evaluate(args=args, state=state, control=None, metrics={"accuracy":0.8, "f1":0.82})
cb.on_save(args=args, state=state, control=None)
cb.on_train_end(args=args, state=state, control=None)
print("Wrote audit events to audit_trail.jsonl")
