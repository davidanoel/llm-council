"""FastAPI backend for cybersecurity prompt annotation."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
from contextlib import asynccontextmanager
from typing import List

from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from . import storage
from .agreement import analyze_export_csv, calculate_agreement
from .council import retry_failed_votes, run_council
from .csv_utils import parse_csv_annotation_file
from .model_provider import (
    close_http_client,
    external_calls_disabled,
    get_council_models,
    get_model_registry,
    get_model_provider_name,
)
from .schemas import (
    AnnotationRequest,
    AnnotationResult,
    AgreementMetrics,
    BatchAnnotationResponse,
    BatchProgress,
    ExportAnalysis,
    ExportManifest,
    ExportPreview,
    ExportedLabel,
    HumanReviewRequest,
    ReviewReasonType,
    RunSummary,
    RunUpdate,
    utc_now,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Close the lazily created shared HTTP client at shutdown."""

    del app
    try:
        yield
    finally:
        await close_http_client()


app = FastAPI(title="Cybersecurity Prompt Labelling API", lifespan=lifespan)
MAX_PROMPT_CONCURRENCY = int(os.getenv("MAX_PROMPT_CONCURRENCY", "5"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):(3000|5173|5174|5175)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    """Health check endpoint."""

    return {
        "status": "ok",
        "service": "Cybersecurity Prompt Labelling API",
        "model_provider": get_model_provider_name(),
        "external_calls_disabled": external_calls_disabled(),
    }


async def annotate_prompt(
    request: AnnotationRequest,
    run_id: str,
    row_number: int | None = None,
) -> AnnotationResult:
    """Annotate and store one prompt inside a run."""

    prompt_id = request.prompt_id or f"row_{row_number or 1}"
    existing = storage.load_annotation(prompt_id, run_id=run_id)
    created_at = existing.created_at if existing else utc_now()
    votes, adjudication = await run_council(
        prompt_id,
        request.prompt_text,
        request.response_text,
        request.metadata,
    )
    result = AnnotationResult(
        prompt_id=prompt_id,
        run_id=run_id,
        prompt_text=request.prompt_text,
        response_text=request.response_text,
        metadata=request.metadata,
        row_number=row_number,
        error_message=None,
        votes=votes,
        adjudication=adjudication,
        human_reviews=existing.human_reviews if existing else [],
        created_at=created_at,
        updated_at=utc_now(),
    )
    return storage.save_annotation(result, run_id=run_id, row_number=row_number)


def failed_annotation(
    request: AnnotationRequest,
    run_id: str,
    row_number: int | None,
    error: Exception,
) -> AnnotationResult:
    """Build a persisted failed row for later resume."""

    prompt_id = request.prompt_id or f"row_{row_number or 1}"
    existing = storage.load_annotation(prompt_id, run_id=run_id)
    return AnnotationResult(
        prompt_id=prompt_id,
        run_id=run_id,
        prompt_text=request.prompt_text,
        response_text=request.response_text,
        metadata=request.metadata,
        row_number=row_number,
        error_message=str(error),
        human_reviews=existing.human_reviews if existing else [],
        created_at=existing.created_at if existing else utc_now(),
        updated_at=utc_now(),
    )


@app.post("/api/runs/csv", response_model=BatchAnnotationResponse)
async def create_run_from_csv(
    csv_text: str = Body(..., media_type="text/csv"),
    run_name: str | None = Query(default=None),
    source_filename: str | None = Query(default=None),
) -> BatchAnnotationResponse:
    """Create a run and annotate prompts from CSV text."""

    try:
        parsed = parse_csv_annotation_file(csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    run = storage.create_run(
        name=run_name or source_filename or "CSV annotation batch",
        source_filename=source_filename,
        task_type=parsed.task_type,
        model_config=current_model_snapshot(),
    )
    return await run_annotation_batch(parsed.prompts, run)


@app.post("/api/runs/csv/validate")
async def validate_annotation_csv(csv_text: str = Body(..., media_type="text/csv")) -> dict:
    """Validate CSV input and return a lightweight preview summary."""

    try:
        parsed = parse_csv_annotation_file(csv_text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {
        "valid_rows": parsed.valid_rows,
        "task_type": parsed.task_type,
        "rows_with_response": parsed.rows_with_response,
        "rows_without_response": parsed.rows_without_response,
        "skipped_empty_prompt_rows": parsed.skipped_empty_prompt_rows,
        "mixed_task_warning": parsed.mixed_task_warning,
    }


async def run_annotation_batch(
    prompts: List[AnnotationRequest],
    run: RunSummary,
) -> BatchAnnotationResponse:
    """Run a bounded-concurrency in-process annotation batch."""

    progress = BatchProgress(total=len(prompts))
    semaphore = asyncio.Semaphore(MAX_PROMPT_CONCURRENCY)
    storage.set_run_status(run.run_id, "running", completed_at=None)

    async def run_one(index_and_prompt: tuple[int, AnnotationRequest]) -> AnnotationResult | None:
        nonlocal progress
        index, prompt = index_and_prompt
        async with semaphore:
            try:
                result = await annotate_prompt(prompt, run_id=run.run_id, row_number=index)
                progress.completed += 1
                if result.adjudication:
                    if result.adjudication.decision_type == "auto_safe":
                        progress.auto_safe += 1
                    elif result.adjudication.decision_type == "auto_unsafe":
                        progress.auto_unsafe += 1
                    else:
                        progress.human_review += 1
                    if all_stage1_votes_provider_failed(result):
                        progress.provider_failed += 1
                else:
                    progress.failed += 1
                return result
            except Exception as exc:
                failed = failed_annotation(prompt, run.run_id, index, error=exc)
                try:
                    failed = storage.save_annotation(failed, run_id=run.run_id, row_number=index)
                except Exception:
                    pass
                progress.failed += 1
                return failed

    raw_results = await asyncio.gather(
        *(run_one((index, prompt)) for index, prompt in enumerate(prompts, start=1))
    )
    results = [result for result in raw_results if result is not None]
    run = storage.complete_run(run.run_id, "completed" if progress.failed == 0 else "failed")
    return BatchAnnotationResponse(results=results, progress=progress, run=run)


def all_stage1_votes_provider_failed(result: AnnotationResult) -> bool:
    """Return whether every Stage 1 vote is a provider/parse failure."""

    if not result.votes:
        return False
    return all(
        vote.parse_error is not None or "provider_failure" in vote.policy_triggers
        for vote in result.votes
    )


def count_result(progress: BatchProgress, result: AnnotationResult) -> None:
    """Update progress counters from a stored annotation result."""

    if not result.adjudication:
        progress.failed += 1
        return
    progress.completed += 1
    if result.adjudication.decision_type == "auto_safe":
        progress.auto_safe += 1
    elif result.adjudication.decision_type == "auto_unsafe":
        progress.auto_unsafe += 1
    else:
        progress.human_review += 1
    if all_stage1_votes_provider_failed(result):
        progress.provider_failed += 1


@app.get("/api/runs", response_model=List[RunSummary])
async def list_runs() -> List[RunSummary]:
    """List annotation runs."""

    return storage.list_runs()


@app.get("/api/runs/{run_id}", response_model=RunSummary)
async def get_run(run_id: str) -> RunSummary:
    """Load one annotation run."""

    run = storage.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.patch("/api/runs/{run_id}", response_model=RunSummary)
async def update_run(run_id: str, request: RunUpdate) -> RunSummary:
    """Update editable run fields."""

    try:
        return storage.rename_run(run_id, request.name)
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found") from None


@app.get("/api/runs/{run_id}/items", response_model=List[AnnotationResult])
async def list_run_items(run_id: str) -> List[AnnotationResult]:
    """List annotations in one run."""

    if not storage.load_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return storage.list_annotations(run_id=run_id)


@app.post("/api/runs/{run_id}/retry-provider-failures", response_model=BatchAnnotationResponse)
async def retry_run_provider_failures(run_id: str) -> BatchAnnotationResponse:
    """Retry failed model votes for non-reviewed items in a run."""

    run = storage.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    retryable = storage.list_retryable_annotations(run_id)
    progress = BatchProgress(total=len(retryable))
    semaphore = asyncio.Semaphore(MAX_PROMPT_CONCURRENCY)

    async def retry_one(annotation: AnnotationResult) -> AnnotationResult | None:
        nonlocal progress
        async with semaphore:
            try:
                votes, adjudication = await retry_failed_votes(annotation)
                annotation.votes = votes
                annotation.adjudication = adjudication
                stored = storage.save_annotation(
                    annotation,
                    run_id=run_id,
                    row_number=annotation.row_number,
                )
                progress.completed += 1
                if adjudication.decision_type == "auto_safe":
                    progress.auto_safe += 1
                elif adjudication.decision_type == "auto_unsafe":
                    progress.auto_unsafe += 1
                else:
                    progress.human_review += 1
                if all_stage1_votes_provider_failed(stored):
                    progress.provider_failed += 1
                return stored
            except Exception:
                progress.failed += 1
                return None

    raw_results = await asyncio.gather(*(retry_one(annotation) for annotation in retryable))
    results = [result for result in raw_results if result is not None]
    return BatchAnnotationResponse(results=results, progress=progress, run=storage.load_run(run_id))


@app.post("/api/runs/{run_id}/resume", response_model=BatchAnnotationResponse)
async def resume_run(run_id: str) -> BatchAnnotationResponse:
    """Resume app-level failed or incomplete rows in a run."""

    run = storage.load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    resumable = storage.list_resumable_annotations(run_id)
    progress = BatchProgress(total=len(resumable))
    semaphore = asyncio.Semaphore(MAX_PROMPT_CONCURRENCY)
    storage.set_run_status(run_id, "running", completed_at=None)

    async def resume_one(annotation: AnnotationResult) -> AnnotationResult:
        async with semaphore:
            request = AnnotationRequest(
                prompt_id=annotation.prompt_id,
                prompt_text=annotation.prompt_text,
                response_text=annotation.response_text,
                metadata=annotation.metadata,
            )
            try:
                result = await annotate_prompt(
                    request,
                    run_id=run_id,
                    row_number=annotation.row_number,
                )
                count_result(progress, result)
                return result
            except Exception as exc:
                failed = failed_annotation(request, run_id, annotation.row_number, exc)
                failed = storage.save_annotation(
                    failed,
                    run_id=run_id,
                    row_number=annotation.row_number,
                )
                progress.failed += 1
                return failed

    results = list(await asyncio.gather(*(resume_one(annotation) for annotation in resumable)))
    status = "failed" if progress.failed else "completed"
    run = storage.complete_run(run_id, status)
    return BatchAnnotationResponse(results=results, progress=progress, run=run)


@app.get("/api/runs/{run_id}/agreement", response_model=AgreementMetrics)
async def run_agreement(run_id: str) -> AgreementMetrics:
    """Report agreement among complete AI annotation panels in one run."""

    if not storage.load_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return calculate_agreement(storage.list_annotations(run_id=run_id))


@app.post("/api/exports/analyze-csv", response_model=ExportAnalysis)
async def agreement_from_csv(csv_text: str = Body(..., media_type="text/csv")) -> ExportAnalysis:
    """Recompute metrics from a previously exported labels CSV."""

    try:
        return analyze_export_csv(csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/runs/{run_id}/review-queue", response_model=List[AnnotationResult])
async def get_run_review_queue(
    run_id: str,
    reason_type: ReviewReasonType | None = Query(default=None),
) -> List[AnnotationResult]:
    """List annotations requiring human review in one run."""

    if not storage.load_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    items = storage.review_queue(run_id=run_id)
    if reason_type and reason_type != "none":
        return [item for item in items if item.review_reason_type == reason_type]
    return items


@app.post("/api/human-review", response_model=AnnotationResult)
async def human_review(request: HumanReviewRequest) -> AnnotationResult:
    """Store a human override."""

    try:
        return storage.add_human_review(request)
    except KeyError:
        raise HTTPException(status_code=404, detail="Annotation not found") from None


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str) -> dict:
    """Delete one run and its annotations."""

    deleted = storage.delete_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"deleted": True, "run_id": run_id}


@app.delete("/api/runs/{run_id}/items/{prompt_id}")
async def delete_annotation(run_id: str, prompt_id: str) -> dict:
    """Delete one stored annotation."""

    deleted = storage.delete_annotation(prompt_id, run_id=run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"deleted": True, "prompt_id": prompt_id}


@app.get("/api/runs/{run_id}/export-labels", response_model=List[ExportedLabel])
async def export_run_labels(
    run_id: str,
    include_prompt_text: bool = Query(default=False),
) -> List[ExportedLabel]:
    """Export labels for one run, preferring human overrides."""

    if not storage.load_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return storage.export_labels(include_prompt_text=include_prompt_text, run_id=run_id)


@app.get("/api/runs/{run_id}/export-preview", response_model=ExportPreview)
async def export_run_preview(run_id: str) -> ExportPreview:
    """Preview export readiness for one run."""

    try:
        return storage.export_preview(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found") from None


@app.get("/api/runs/{run_id}/export-manifest", response_model=ExportManifest)
async def export_run_manifest(run_id: str) -> ExportManifest:
    """Return an export manifest for one run."""

    try:
        return storage.export_manifest(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found") from None


@app.get("/api/runs/{run_id}/export-labels.csv")
async def export_run_labels_csv(
    run_id: str,
    include_prompt_text: bool = Query(default=False),
) -> Response:
    """Export labels for one run as CSV."""

    if not storage.load_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    labels = storage.export_labels(include_prompt_text=include_prompt_text, run_id=run_id)
    csv_text = labels_to_csv(labels)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="labels.csv"'},
    )


def current_model_snapshot() -> dict:
    """Snapshot model configuration for a run."""

    return {
        "provider": get_model_provider_name(),
        "models": get_council_models(),
        "registry": get_model_registry(),
    }


def labels_to_csv(labels: List[ExportedLabel]) -> str:
    """Serialize exported labels to CSV."""

    output = io.StringIO()
    fieldnames = [
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
        "created_at",
        "updated_at",
        "metadata",
    ]
    vote_fields = ["model", "label", "confidence", "unsafe_category", "parse_error", "rationale"]
    fieldnames.extend(
        f"vote_{index}_{field}"
        for index in range(1, 4)
        for field in vote_fields
    )
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for label in labels:
        row = {
            "run_id": label.run_id,
            "run_name": label.run_name,
            "task_type": label.task_type,
            "row_number": "" if label.row_number is None else label.row_number,
            "prompt_id": label.prompt_id,
            "prompt": label.prompt_text or "",
            "response": label.response_text or "",
            "label": label.label,
            "label_source": label.label_source,
            "decision_type": label.decision_type,
            "review_reason_type": label.review_reason_type,
            "confidence": "" if label.confidence is None else label.confidence,
            "unsafe_category": label.unsafe_category,
            "human_review_rationale": label.human_review_rationale or "",
            "created_at": label.created_at,
            "updated_at": label.updated_at,
            "metadata": json.dumps(label.metadata, sort_keys=True),
        }
        for index in range(1, 4):
            vote = label.votes[index - 1] if index <= len(label.votes) else None
            row.update(
                {
                    f"vote_{index}_model": vote.model_name if vote else "",
                    f"vote_{index}_label": vote.label if vote else "",
                    f"vote_{index}_confidence": vote.confidence if vote else "",
                    f"vote_{index}_unsafe_category": vote.unsafe_category if vote else "",
                    f"vote_{index}_parse_error": vote.parse_error if vote else "",
                    f"vote_{index}_rationale": vote.rationale if vote else "",
                }
            )
        writer.writerow(row)
    return output.getvalue()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
