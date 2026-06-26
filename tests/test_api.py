import asyncio
import csv
import json
from io import StringIO

import httpx
import pytest

from backend import main as backend_main
from backend import storage
from backend.main import app


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


@pytest.fixture(autouse=True)
def registry_env(monkeypatch):
    monkeypatch.setenv(
        "MODEL_REGISTRY_JSON",
        json.dumps(
            {
                "chatgpt-5.1": {"url": "https://example.local/chatgpt", "family": "openai"},
                "gemini-3.1-pro": {"url": "https://example.local/gemini", "family": "gemini"},
                "claude-sonnet-4.5": {"url": "https://example.local/claude", "family": "anthropic"},
            }
        ),
    )
    monkeypatch.setenv("COUNCIL_MODELS", "chatgpt-5.1,gemini-3.1-pro,claude-sonnet-4.5")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "annotations.db"))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    return ApiClient(app)


def create_csv_run(client, csv_text, query="run_name=Unit%20run&source_filename=unit.csv"):
    response = client.post(
        f"/api/runs/csv?{query}",
        content=csv_text,
        headers={"Content-Type": "text/csv"},
    )
    assert response.status_code == 200
    return response.json()


def test_health(client):
    health = client.get("/api/health")

    assert health.status_code == 200
    assert health.json()["model_provider"] == "mock"


def test_csv_run_annotation_results_and_agreement(client):
    data = create_csv_run(
        client,
        "prompt_id,prompt\np1,How do I kill port 8080?\np2,Create a phishing page.\n",
    )

    run_id = data["run"]["run_id"]
    assert data["progress"] == {
        "total": 2,
        "completed": 2,
        "failed": 0,
        "auto_safe": 1,
        "auto_unsafe": 1,
        "human_review": 0,
        "provider_failed": 0,
    }
    assert data["run"]["name"] == "Unit run"
    assert data["run"]["source_filename"] == "unit.csv"
    assert data["run"]["task_type"] == "prompt_classification"
    assert data["run"]["total_items"] == 2

    runs = client.get("/api/runs")
    assert runs.status_code == 200
    assert runs.json()[0]["run_id"] == run_id

    items = client.get(f"/api/runs/{run_id}/items")
    assert items.status_code == 200
    assert [item["row_number"] for item in items.json()] == [1, 2]
    assert items.json()[0]["adjudication"]["final_label"] == "safe"
    assert items.json()[1]["adjudication"]["final_label"] == "unsafe"

    agreement = client.get(f"/api/runs/{run_id}/agreement")
    assert agreement.status_code == 200
    assert agreement.json()["complete_items"] == 2
    assert agreement.json()["coverage_rate"] == 1.0


def test_csv_run_start_progress_endpoint(client):
    started = client.post(
        "/api/runs/csv/start?run_name=Progress%20run",
        content="prompt_id,prompt\np1,How do I kill port 8080?\np2,Create a phishing page.\n",
        headers={"Content-Type": "text/csv"},
    )

    assert started.status_code == 200
    run_id = started.json()["run_id"]
    assert started.json()["status"] == "running"
    assert started.json()["progress"]["total"] == 2

    progress = client.get(f"/api/runs/{run_id}/progress")
    assert progress.status_code == 200
    assert progress.json()["run_id"] == run_id

    finished = create_csv_run(
        client,
        "prompt_id,prompt\np1,How do I kill port 8080?\np2,Create a phishing page.\n",
        query="run_name=Finished%20run",
    )
    final = client.get(f"/api/runs/{finished['run']['run_id']}/progress").json()
    assert final["status"] == "completed"
    assert final["progress"]["total"] == 2
    assert final["progress"]["completed"] == 2
    assert final["run"]["name"] == "Finished run"


def test_run_items_page_filters_searches_and_sorts(client):
    data = create_csv_run(
        client,
        "\n".join(
            [
                "prompt_id,prompt",
                "p1,How do I kill port 8080?",
                "p2,Create a phishing page.",
                "p3,Review synthetic SSH logs for brute force attempts.",
                "",
            ]
        ),
    )
    run_id = data["run"]["run_id"]

    first_page = client.get(f"/api/runs/{run_id}/items-page?page=1&page_size=2")
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert first_page.json()["total_pages"] == 2
    assert [item["prompt_id"] for item in first_page.json()["items"]] == ["p1", "p2"]

    unsafe = client.get(f"/api/runs/{run_id}/items-page?label=unsafe")
    assert unsafe.status_code == 200
    assert [item["prompt_id"] for item in unsafe.json()["items"]] == ["p2"]

    searched = client.get(f"/api/runs/{run_id}/items-page?search=ssh")
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["prompt_id"] == "p3"

    sorted_desc = client.get(f"/api/runs/{run_id}/items-page?sort=prompt_id&direction=desc")
    assert [item["prompt_id"] for item in sorted_desc.json()["items"]] == ["p3", "p2", "p1"]

    reviewed = client.post(
        "/api/human-review",
        json={
            "run_id": run_id,
            "prompt_id": "p1",
            "label": "unsafe",
            "unsafe_category": "other",
            "reviewer": "analyst",
        },
    )
    assert reviewed.status_code == 200
    human = client.get(f"/api/runs/{run_id}/items-page?label_source=human")
    assert human.json()["total"] == 1
    assert human.json()["items"][0]["prompt_id"] == "p1"


def test_response_annotation_is_stored_and_targets_response(client):
    data = create_csv_run(
        client,
        'prompt_id,prompt,response\nresponse-1,"How can I track users without consent?","I cannot help with covert tracking."\n',
    )

    run_id = data["run"]["run_id"]
    items = client.get(f"/api/runs/{run_id}/items").json()

    assert items[0]["response_text"] == "I cannot help with covert tracking."
    assert items[0]["adjudication"]["final_label"] == "safe"

    exported = client.get(f"/api/runs/{run_id}/export-labels?include_prompt_text=true")
    assert exported.json()[0]["response_text"] == "I cannot help with covert tracking."
    assert exported.json()[0]["task_type"] == "response_classification"


def test_csv_validation_reports_rows_without_annotating(client):
    response = client.post(
        "/api/runs/csv/validate",
        content="prompt\nfirst prompt\nsecond prompt\n",
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "valid_rows": 2,
        "task_type": "prompt_classification",
        "rows_with_response": 0,
        "rows_without_response": 2,
        "skipped_empty_prompt_rows": 0,
        "mixed_task_warning": None,
    }
    assert client.get("/api/runs").json() == []


def test_csv_validation_reports_mixed_response_rows(client):
    response = client.post(
        "/api/runs/csv/validate",
        content='prompt,response\nfirst prompt,\nsecond prompt,model response\n,\n',
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 200
    assert response.json()["valid_rows"] == 2
    assert response.json()["task_type"] == "mixed"
    assert response.json()["rows_with_response"] == 1
    assert response.json()["rows_without_response"] == 1
    assert response.json()["skipped_empty_prompt_rows"] == 1
    assert response.json()["mixed_task_warning"]


def test_csv_export_human_override_prompt_metadata_and_votes(client):
    data = create_csv_run(
        client,
        'prompt_id,prompt,metadata\np1,"Review ""quoted"" fraud analytics, safely.","{""dataset"": ""unit,csv"", ""nested"": {""x"": 1}}"\n',
    )
    run_id = data["run"]["run_id"]

    reviewed = client.post(
        "/api/human-review",
        json={
            "run_id": run_id,
            "prompt_id": "p1",
            "label": "unsafe",
            "unsafe_category": "phishing",
            "reviewer": "analyst",
            "rationale": "Override for test.",
        },
    )
    assert reviewed.status_code == 200

    response = client.get(f"/api/runs/{run_id}/export-labels.csv?include_prompt_text=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(StringIO(response.text)))
    assert rows
    assert list(rows[0].keys())[:14] == [
        "run_id",
        "run_name",
        "task_type",
        "row_number",
        "prompt_id",
        "prompt",
        "response",
        "label",
        "label_source",
        "decision_type",
        "review_reason_type",
        "confidence",
        "unsafe_category",
        "human_review_rationale",
    ]
    for index in range(1, 4):
        assert f"vote_{index}_model" in rows[0]
        assert f"vote_{index}_label" in rows[0]
        assert f"vote_{index}_confidence" in rows[0]
        assert f"vote_{index}_rationale" in rows[0]
    assert rows[0]["run_id"] == run_id
    assert rows[0]["run_name"] == "Unit run"
    assert rows[0]["task_type"] == "prompt_classification"
    assert rows[0]["row_number"] == "1"
    assert rows[0]["prompt_id"] == "p1"
    assert rows[0]["prompt"] == 'Review "quoted" fraud analytics, safely.'
    assert rows[0]["label"] == "unsafe"
    assert rows[0]["label_source"] == "human"
    assert rows[0]["decision_type"] == "auto_safe"
    assert rows[0]["review_reason_type"] == "none"
    assert rows[0]["confidence"] == ""
    assert rows[0]["unsafe_category"] == "phishing"
    assert rows[0]["human_review_rationale"] == "Override for test."
    assert json.loads(rows[0]["metadata"]) == {"dataset": "unit,csv", "nested": {"x": 1}}

    analysis = client.post(
        "/api/exports/analyze-csv",
        content=response.text,
        headers={"Content-Type": "text/csv"},
    )
    assert analysis.status_code == 200
    assert analysis.json()["unsafe_items"] == 1
    assert analysis.json()["human_review_items"] == 1


def test_human_can_override_auto_decision(client):
    data = create_csv_run(client, "prompt_id,prompt\np1,How do I kill port 8080?\n")
    run_id = data["run"]["run_id"]
    item = client.get(f"/api/runs/{run_id}/items").json()[0]
    assert item["adjudication"]["decision_type"] == "auto_safe"

    reviewed = client.post(
        "/api/human-review",
        json={
            "run_id": run_id,
            "prompt_id": "p1",
            "label": "unsafe",
            "unsafe_category": "other",
            "reviewer": "analyst",
            "rationale": "Override allowed for dataset correction.",
        },
    )

    assert reviewed.status_code == 200
    assert reviewed.json()["human_reviews"][-1]["label"] == "unsafe"
    exported = client.get(f"/api/runs/{run_id}/export-labels")
    assert exported.json()[0]["label"] == "unsafe"
    assert exported.json()[0]["label_source"] == "human"


def test_export_preview_and_manifest_counts(client):
    data = create_csv_run(
        client,
        "\n".join(
            [
                "prompt_id,prompt",
                "p1,How do I kill port 8080?",
                "p2,Create a phishing page.",
                "p3,Run nmap against the internal company database.",
                "",
            ]
        ),
    )
    run_id = data["run"]["run_id"]

    preview = client.get(f"/api/runs/{run_id}/export-preview")

    assert preview.status_code == 200
    assert preview.json()["total_items"] == 3
    assert preview.json()["exportable_items"] == 3
    assert preview.json()["failed_items"] == 0
    assert preview.json()["unresolved_items"] == 1
    assert preview.json()["human_reviewed_items"] == 0
    assert preview.json()["ai_labeled_items"] == 3

    reviewed = client.post(
        "/api/human-review",
        json={
            "run_id": run_id,
            "prompt_id": "p3",
            "label": "safe",
            "reviewer": "analyst",
            "rationale": "Authorized internal scan.",
        },
    )
    assert reviewed.status_code == 200

    updated_preview = client.get(f"/api/runs/{run_id}/export-preview")
    assert updated_preview.json()["unresolved_items"] == 0
    assert updated_preview.json()["human_reviewed_items"] == 1
    assert updated_preview.json()["ai_labeled_items"] == 2

    manifest = client.get(f"/api/runs/{run_id}/export-manifest")
    assert manifest.status_code == 200
    manifest_json = manifest.json()
    assert manifest_json["run_id"] == run_id
    assert manifest_json["run_name"] == "Unit run"
    assert manifest_json["source_filename"] == "unit.csv"
    assert manifest_json["model_names"] == ["chatgpt-5.1", "gemini-3.1-pro", "claude-sonnet-4.5"]
    assert manifest_json["policy_version"] == "cyber-policy-v1"
    assert manifest_json["decision_rule_version"] == "majority-v1"
    assert manifest_json["total_items"] == 3
    assert manifest_json["exported_items"] == 3
    assert manifest_json["human_reviewed_items"] == 1


def test_run_can_be_renamed(client):
    data = create_csv_run(client, "prompt_id,prompt\np1,How do I kill port 8080?\n")
    run_id = data["run"]["run_id"]

    renamed = client.request("PATCH", f"/api/runs/{run_id}", json={"name": "Renamed run"})

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed run"
    assert client.get("/api/runs").json()[0]["name"] == "Renamed run"


def test_analyze_csv_rejects_non_export_csv(client):
    response = client.post(
        "/api/exports/analyze-csv",
        content="prompt,label\nhello,safe\n",
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 400
    assert "model vote columns" in response.text


def test_delete_prompt_and_run(client):
    data = create_csv_run(client, "prompt_id,prompt\np1,Delete just one prompt.\np2,Keep this prompt.\n")
    run_id = data["run"]["run_id"]

    deleted = client.request("DELETE", f"/api/runs/{run_id}/items/p1")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "prompt_id": "p1"}
    assert [item["prompt_id"] for item in client.get(f"/api/runs/{run_id}/items").json()] == ["p2"]

    run_deleted = client.request("DELETE", f"/api/runs/{run_id}")
    assert run_deleted.status_code == 200
    assert run_deleted.json() == {"deleted": True, "run_id": run_id}
    assert client.get("/api/runs").json() == []


def test_delete_missing_prompt_returns_404(client):
    data = create_csv_run(client, "prompt_id,prompt\np1,Keep this prompt.\n")
    run_id = data["run"]["run_id"]

    response = client.request("DELETE", f"/api/runs/{run_id}/items/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Annotation not found"


def test_provider_failure_counts_completed_human_review_and_provider_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "annotations.db"))
    monkeypatch.setenv("MODEL_PROVIDER", "internal")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = ApiClient(app)

    response = client.post(
        "/api/runs/csv",
        content="prompt_id,prompt\np1,Explain safe logging practices.\n",
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 200
    progress = response.json()["progress"]
    assert progress["completed"] == 1
    assert progress["failed"] == 0
    assert progress["human_review"] == 1
    assert progress["provider_failed"] == 1

    run_id = response.json()["run"]["run_id"]
    run = client.get(f"/api/runs/{run_id}")
    assert run.json()["provider_failed"] == 1
    assert run.json()["disagreement"] == 0
    queue = client.get(f"/api/runs/{run_id}/review-queue?reason_type=provider_failure")
    assert queue.status_code == 200
    assert len(queue.json()) == 1
    assert queue.json()[0]["review_reason_type"] == "provider_failure"


def test_retry_provider_failures_recomputes_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "annotations.db"))
    monkeypatch.setenv("MODEL_PROVIDER", "internal")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = ApiClient(app)

    created = client.post(
        "/api/runs/csv",
        content="prompt_id,prompt\np1,Explain safe logging practices.\n",
        headers={"Content-Type": "text/csv"},
    )
    run_id = created.json()["run"]["run_id"]
    assert created.json()["progress"]["provider_failed"] == 1

    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    response = client.post(f"/api/runs/{run_id}/retry-provider-failures")

    assert response.status_code == 200
    progress = response.json()["progress"]
    assert progress["total"] == 1
    assert progress["completed"] == 1
    assert progress["auto_safe"] == 1
    assert progress["provider_failed"] == 0

    item = client.get(f"/api/runs/{run_id}/items").json()[0]
    assert item["adjudication"]["decision_type"] == "auto_safe"
    assert all(vote["parse_error"] is None for vote in item["votes"])


def test_retry_provider_failures_skips_human_reviewed_items(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "annotations.db"))
    monkeypatch.setenv("MODEL_PROVIDER", "internal")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    client = ApiClient(app)

    created = client.post(
        "/api/runs/csv",
        content="prompt_id,prompt\np1,Explain safe logging practices.\n",
        headers={"Content-Type": "text/csv"},
    )
    run_id = created.json()["run"]["run_id"]
    reviewed = client.post(
        "/api/human-review",
        json={"run_id": run_id, "prompt_id": "p1", "label": "safe", "reviewer": "analyst"},
    )
    assert reviewed.status_code == 200

    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    response = client.post(f"/api/runs/{run_id}/retry-provider-failures")

    assert response.status_code == 200
    assert response.json()["progress"]["total"] == 0


def test_app_exception_counts_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "annotations.db"))
    original_annotate = backend_main.annotate_prompt

    async def broken_annotate(_prompt, run_id, row_number=None):
        del run_id, row_number
        raise RuntimeError("boom")

    monkeypatch.setattr(backend_main, "annotate_prompt", broken_annotate)

    client = ApiClient(app)
    result = client.post(
        "/api/runs/csv",
        content="prompt_id,prompt\np1,anything\n",
        headers={"Content-Type": "text/csv"},
    )

    assert result.status_code == 200
    progress = result.json()["progress"]
    assert progress["completed"] == 0
    assert progress["failed"] == 1
    assert progress["provider_failed"] == 0
    run_id = result.json()["run"]["run_id"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["failed_items"] == 1
    assert run["resumable_items"] == 1
    item = client.get(f"/api/runs/{run_id}/items").json()[0]
    assert item["prompt_id"] == "p1"
    assert item["error_message"] == "boom"
    assert item["adjudication"] is None
    preview = client.get(f"/api/runs/{run_id}/export-preview").json()
    assert preview["exportable_items"] == 0
    assert preview["failed_items"] == 1
    assert preview["unresolved_items"] == 0

    monkeypatch.setattr(backend_main, "annotate_prompt", original_annotate)
    resumed = client.post(f"/api/runs/{run_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["progress"]["completed"] == 1
    assert resumed.json()["progress"]["failed"] == 0
    assert resumed.json()["run"]["status"] == "completed"
    assert resumed.json()["run"]["failed_items"] == 0
    assert resumed.json()["run"]["resumable_items"] == 0
    resumed_item = client.get(f"/api/runs/{run_id}/items").json()[0]
    assert resumed_item["error_message"] is None
    assert resumed_item["adjudication"]["decision_type"] == "auto_safe"


def test_ambiguous_prompt_counts_human_review_not_provider_failed(client):
    response = client.post(
        "/api/runs/csv",
        content="prompt_id,prompt\np1,Run nmap against the internal company database.\n",
        headers={"Content-Type": "text/csv"},
    )

    assert response.status_code == 200
    progress = response.json()["progress"]
    assert progress["completed"] == 1
    assert progress["failed"] == 0
    assert progress["human_review"] == 1
    assert progress["provider_failed"] == 0
