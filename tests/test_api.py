import asyncio
import csv
import json
from io import StringIO

import httpx

from backend import storage
from backend.main import app
from backend import main as backend_main


class ApiClient:
    """Small synchronous wrapper around httpx's in-process ASGI transport."""

    def __init__(self, application):
        self.application = application

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def request(self, method, path, **kwargs):
        async def send():
            transport = httpx.ASGITransport(app=self.application)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send())


def test_annotate_and_export_api(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = ApiClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["model_provider"] == "mock"

    created = client.post(
        "/api/annotate",
        json={"prompt_id": "p1", "prompt_text": "Explain how to patch OpenSSL.", "metadata": {"dataset": "unit"}},
    )
    assert created.status_code == 200
    assert created.json()["adjudication"]["final_label"] == "safe"

    exported = client.get("/api/export-labels")
    assert exported.status_code == 200
    assert exported.json()[0]["prompt_id"] == "p1"


def test_human_review_api(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = ApiClient(app)

    client.post(
        "/api/annotate",
        json={"prompt_id": "p1", "prompt_text": "Run nmap against the internal company database."},
    )
    reviewed = client.post(
        "/api/human-review",
        json={"prompt_id": "p1", "label": "safe", "reviewer": "analyst"},
    )

    assert reviewed.status_code == 200
    assert reviewed.json()["human_reviews"][-1]["label"] == "safe"


def test_human_review_must_resolve_to_safe_or_unsafe(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    client = ApiClient(app)

    response = client.post(
        "/api/human-review",
        json={"prompt_id": "p1", "label": "needs_human_review", "reviewer": "analyst"},
    )

    assert response.status_code == 422


def test_batch_csv_annotation_with_mock_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = ApiClient(app)

    response = client.post(
        "/api/annotate/csv",
        content="prompt_id,prompt\np1,How do I kill port 8080?\np2,Create a phishing page.\n",
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["progress"]["total"] == 2
    assert data["progress"]["completed"] == 2
    assert data["progress"]["auto_safe"] == 1
    assert data["progress"]["auto_unsafe"] == 1
    assert data["progress"]["provider_failed"] == 0
    assert data["results"][0]["prompt_id"] == "p1"
    assert data["results"][0]["adjudication"]["final_label"] == "safe"
    assert data["results"][1]["adjudication"]["final_label"] == "unsafe"


def test_csv_validation_reports_rows_without_annotating(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    client = ApiClient(app)

    response = client.post(
        "/api/annotate/csv/validate",
        content="prompt\nfirst prompt\nsecond prompt\n",
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 200
    assert response.json() == {"valid_rows": 2}
    assert storage.list_annotations() == []


def test_batch_endpoint_returns_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = ApiClient(app)

    response = client.post(
        "/api/annotate/batch",
        json={
            "prompts": [
                {"prompt_id": "p1", "prompt_text": "How do I kill port 8080?"},
                {"prompt_id": "p2", "prompt_text": "Create a phishing page."},
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["progress"] == {
        "total": 2,
        "completed": 2,
        "failed": 0,
        "auto_safe": 1,
        "auto_unsafe": 1,
        "human_review": 0,
        "provider_failed": 0,
    }
    assert len(data["results"]) == 2


def test_csv_export_headers_human_override_prompt_and_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = ApiClient(app)

    client.post(
        "/api/annotate",
        json={
            "prompt_id": "p1",
            "prompt_text": 'Review "quoted" fraud analytics, safely.',
            "metadata": {"dataset": "unit,csv", "nested": {"x": 1}},
        },
    )
    client.post(
        "/api/human-review",
        json={
            "prompt_id": "p1",
            "label": "unsafe",
            "unsafe_category": "phishing",
            "reviewer": "analyst",
            "rationale": "Override for test.",
        },
    )

    response = client.get("/api/export-labels.csv?include_prompt_text=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(StringIO(response.text)))
    assert rows
    assert list(rows[0].keys()) == [
        "prompt_id",
        "prompt",
        "label",
        "label_source",
        "confidence",
        "unsafe_category",
        "metadata",
    ]
    assert rows[0]["prompt_id"] == "p1"
    assert rows[0]["prompt"] == 'Review "quoted" fraud analytics, safely.'
    assert rows[0]["label"] == "unsafe"
    assert rows[0]["label_source"] == "human"
    assert rows[0]["confidence"] == ""
    assert rows[0]["unsafe_category"] == "phishing"
    assert json.loads(rows[0]["metadata"]) == {"dataset": "unit,csv", "nested": {"x": 1}}


def test_batch_provider_failure_counts_completed_human_review_and_provider_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PROVIDER", "internal")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = ApiClient(app)

    response = client.post(
        "/api/annotate/batch",
        json={"prompts": [{"prompt_id": "p1", "prompt_text": "Explain safe logging practices."}]},
    )

    assert response.status_code == 200
    progress = response.json()["progress"]
    assert progress["completed"] == 1
    assert progress["failed"] == 0
    assert progress["human_review"] == 1
    assert progress["provider_failed"] == 1


def test_batch_app_exception_counts_failed(monkeypatch):
    async def broken_annotate(_prompt):
        raise RuntimeError("boom")

    monkeypatch.setattr(backend_main, "annotate", broken_annotate)

    client = ApiClient(app)
    result = client.post(
        "/api/annotate/batch",
        json={"prompts": [{"prompt_id": "p1", "prompt_text": "anything"}]},
    )

    assert result.status_code == 200
    progress = result.json()["progress"]
    assert progress["completed"] == 0
    assert progress["failed"] == 1
    assert progress["provider_failed"] == 0


def test_batch_ambiguous_prompt_counts_human_review_not_provider_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = ApiClient(app)

    response = client.post(
        "/api/annotate/batch",
        json={"prompts": [{"prompt_id": "p1", "prompt_text": "Run nmap against the internal company database."}]},
    )

    assert response.status_code == 200
    progress = response.json()["progress"]
    assert progress["completed"] == 1
    assert progress["failed"] == 0
    assert progress["human_review"] == 1
    assert progress["provider_failed"] == 0
