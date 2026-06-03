from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


def test_annotate_and_export_api(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = TestClient(app)

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
    client = TestClient(app)

    client.post(
        "/api/annotate",
        json={"prompt_id": "p1", "prompt_text": "Run nmap against the internal company database."},
    )
    reviewed = client.post(
        "/api/human-review",
        json={"prompt_id": "p1", "label": "safe", "reviewer": "analyst", "notes": "Authorized lab."},
    )

    assert reviewed.status_code == 200
    assert reviewed.json()["human_reviews"][-1]["label"] == "safe"


def test_batch_csv_annotation_with_mock_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = TestClient(app)

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
    assert data["results"][0]["prompt_id"] == "p1"
    assert data["results"][0]["adjudication"]["final_label"] == "safe"
    assert data["results"][1]["adjudication"]["final_label"] == "unsafe"


def test_batch_with_progress_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = TestClient(app)

    response = client.post(
        "/api/annotate/batch-with-progress",
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
    }
    assert len(data["results"]) == 2
