"""Optional extras, helper events, and packaged resources."""

from __future__ import annotations

import importlib.util
import json

import pytest

from llm_audit_trail import (
    AuditLogger,
    EventTypes,
    dataset_attestation,
    iter_events,
    record_approval,
    record_attestation,
    record_waiver,
    register_dataset,
    verify_log,
)
from llm_audit_trail.registry import available_schemas, load_schema

_HAS_TRANSFORMERS = importlib.util.find_spec("transformers") is not None
_HAS_STARLETTE = importlib.util.find_spec("starlette") is not None


# --------------------------------------------------------------------------
# the core must not depend on the extras
# --------------------------------------------------------------------------


def test_core_imports_without_optional_dependencies():
    import llm_audit_trail

    assert llm_audit_trail.AuditLogger is not None
    assert llm_audit_trail.__version__


@pytest.mark.skipif(_HAS_TRANSFORMERS, reason="transformers is installed")
def test_missing_hf_extra_raises_a_useful_error():
    from llm_audit_trail import hf_audit_callback

    with pytest.raises(ImportError, match=r"llm-audit-trail\[hf\]"):
        hf_audit_callback(model_id="m1")


# --------------------------------------------------------------------------
# governance and provenance helpers
# --------------------------------------------------------------------------


def test_governance_helpers_write_verifiable_events(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLogger(path=path)
    scope = {"model_id": "m1", "deployment_id": "prod-1"}

    record_approval(log, owner="MRC", rationale="meets thresholds", scope=scope)
    record_waiver(
        log,
        owner="MRC",
        rationale="pilot",
        scope=scope,
        waived_controls=["SLO:latency_p95"],
        time_bound_until="2026-12-31",
    )
    record_attestation(log, owner="Compliance", statement="in scope", scope=scope)

    ok, report = verify_log(path)
    assert ok, report

    events = list(iter_events(path))
    assert [e["event_type"] for e in events] == [
        EventTypes.APPROVAL,
        EventTypes.RISK_WAIVER,
        EventTypes.ATTESTATION,
    ]
    assert all(e["system"] == "governance" for e in events)
    assert all(e["model_id"] == "m1" for e in events)
    assert events[0]["actor"] == "MRC"


def test_scope_keys_absent_from_the_dict_become_null(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLogger(path=path)
    record_approval(log, owner="MRC", rationale="ok", scope={"model_id": "m1"})

    event = next(iter_events(path))
    assert event["dataset_id"] is None
    assert event["deployment_id"] is None


def test_dataset_provenance_events(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLogger(path=path)

    register_dataset(
        log,
        dataset_id="hf:stanfordnlp/imdb",
        version="latest",
        source="huggingface://datasets/stanfordnlp/imdb",
        rows=100_000,
        license="unknown",
        content_hash="sha256:abc",
        preprocessing={"splits": ["train", "test"]},
        owner="stanfordnlp",
    )
    dataset_attestation(
        log,
        dataset_id="hf:stanfordnlp/imdb",
        statement="licensed for research",
        owner="Compliance",
    )

    ok, report = verify_log(path)
    assert ok, report
    events = list(iter_events(path))
    assert events[0]["details"]["rows"] == 100_000
    assert events[0]["dataset_id"] == "hf:stanfordnlp/imdb"


# --------------------------------------------------------------------------
# packaged schemas
# --------------------------------------------------------------------------


def test_bundled_schemas_are_installed_and_loadable():
    assert available_schemas() == [
        "Approval",
        "Attestation",
        "DatasetRegistered",
        "RiskWaiver",
    ]
    for event_type in available_schemas():
        schema = load_schema(event_type)
        assert schema["type"] == "object"
        assert "properties" in schema


def test_unknown_schema_names_the_alternatives():
    with pytest.raises(KeyError, match="Approval"):
        load_schema("NoSuchEvent")


# --------------------------------------------------------------------------
# fastapi middleware
# --------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_STARLETTE, reason="starlette is not installed")
def test_middleware_passes_requests_through_and_logs_them(tmp_path):
    from fastapi import Body, FastAPI
    from fastapi.testclient import TestClient

    from llm_audit_trail import AuditMiddleware

    path = str(tmp_path / "audit.jsonl")
    log = AuditLogger(path=path, system="fastapi")

    app = FastAPI()
    app.add_middleware(AuditMiddleware, logger=log, model_id="demo-v1")

    @app.post("/infer")
    def infer(payload: dict = Body(...)):
        return {"echo": payload["prompt"]}

    client = TestClient(app)
    response = client.post("/infer", json={"prompt": "hello"})

    # the endpoint still receives its body, and the response still reaches
    # the client: both broke in earlier versions of this middleware
    assert response.status_code == 200
    assert response.json() == {"echo": "hello"}

    ok, report = verify_log(path)
    assert ok, report
    events = list(iter_events(path))
    assert [e["event_type"] for e in events] == [
        "InferenceRequest",
        "InferenceResponse",
    ]
    assert events[0]["details"]["request_id"] == events[1]["details"]["request_id"]
    assert events[0]["model_id"] == "demo-v1"


@pytest.mark.skipif(not _HAS_STARLETTE, reason="starlette is not installed")
def test_middleware_redacts_bodies_and_ip_by_default(tmp_path):
    from fastapi import Body, FastAPI
    from fastapi.testclient import TestClient

    from llm_audit_trail import AuditMiddleware

    path = str(tmp_path / "audit.jsonl")
    app = FastAPI()
    app.add_middleware(AuditMiddleware, logger=AuditLogger(path=path))

    @app.post("/infer")
    def infer(payload: dict = Body(...)):
        return {"secret": "s3cret-completion"}

    TestClient(app).post("/infer", json={"prompt": "private-prompt"})

    raw = (tmp_path / "audit.jsonl").read_text()
    assert "private-prompt" not in raw
    assert "s3cret-completion" not in raw
    assert "client_ip" not in raw

    request_event = list(iter_events(path))[0]
    assert request_event["details"]["body_preview"] is None
    assert request_event["details"]["body_hash"].startswith("sha256:")


@pytest.mark.skipif(not _HAS_STARLETTE, reason="starlette is not installed")
def test_middleware_can_record_previews_when_asked(tmp_path):
    from fastapi import Body, FastAPI
    from fastapi.testclient import TestClient

    from llm_audit_trail import AuditMiddleware

    path = str(tmp_path / "audit.jsonl")
    app = FastAPI()
    app.add_middleware(
        AuditMiddleware,
        logger=AuditLogger(path=path),
        redact_previews=False,
        log_client_ip=True,
    )

    @app.post("/infer")
    def infer(payload: dict = Body(...)):
        return {"echo": payload["prompt"]}

    TestClient(app).post("/infer", json={"prompt": "visible"})

    events = list(iter_events(path))
    assert "visible" in events[0]["details"]["body_preview"]
    assert "client_ip" in events[0]["details"]


@pytest.mark.skipif(not _HAS_STARLETTE, reason="starlette is not installed")
def test_streaming_responses_are_not_buffered(tmp_path):
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient

    from llm_audit_trail import AuditMiddleware

    path = str(tmp_path / "audit.jsonl")
    app = FastAPI()
    app.add_middleware(
        AuditMiddleware, logger=AuditLogger(path=path), buffer_response=False
    )

    @app.get("/stream")
    def stream():
        def tokens():
            for word in ["a", "b", "c"]:
                yield word

        return StreamingResponse(tokens(), media_type="text/plain")

    response = TestClient(app).get("/stream")
    assert response.text == "abc"

    events = list(iter_events(path))
    assert events[1]["details"]["streamed"] is True
    assert events[1]["details"]["resp_hash"] is None
