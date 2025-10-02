
# examples/fastapi_app.py
from fastapi import FastAPI
from llm_audit_trail import AuditLogger
from llm_audit_trail.fastapi import AuditMiddleware

app = FastAPI()
log = AuditLogger(system="api")
app.add_middleware(AuditMiddleware, logger=log, redact_previews=True)

@app.post("/infer")
def infer(prompt: str):
    return {"output": prompt[::-1]}
