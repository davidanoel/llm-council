"""FastAPI backend for cybersecurity prompt annotation."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import List

from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from . import storage
from .agreement import calculate_agreement
from .council import run_council
from .csv_utils import parse_csv_annotations
from .model_provider import (
    close_http_client,
    external_calls_disabled,
    get_model_provider_name,
)
from .schemas import (
    AnnotationRequest,
    AnnotationResult,
    AgreementMetrics,
    BatchAnnotationResponse,
    BatchAnnotationRequest,
    BatchProgress,
    ExportedLabel,
    HumanReviewRequest,
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


@app.post("/api/annotate", response_model=AnnotationResult)
async def annotate(request: AnnotationRequest) -> AnnotationResult:
    """Annotate and store one prompt."""

    prompt_id = request.prompt_id or str(uuid.uuid4())
    existing = storage.load_annotation(prompt_id)
    created_at = existing.created_at if existing else utc_now()
    votes, adjudication = await run_council(
        prompt_id,
        request.prompt_text,
        request.response_text,
        request.metadata,
    )
    result = AnnotationResult(
        prompt_id=prompt_id,
        prompt_text=request.prompt_text,
        response_text=request.response_text,
        metadata=request.metadata,
        votes=votes,
        adjudication=adjudication,
        human_reviews=existing.human_reviews if existing else [],
        created_at=created_at,
        updated_at=utc_now(),
    )
    return storage.save_annotation(result)


@app.post("/api/annotate/batch", response_model=BatchAnnotationResponse)
async def annotate_batch(request: BatchAnnotationRequest) -> BatchAnnotationResponse:
    """Annotate and store multiple prompts."""

    return await run_annotation_batch(request.prompts)


@app.post("/api/annotate/csv", response_model=BatchAnnotationResponse)
async def annotate_csv(csv_text: str = Body(..., media_type="text/csv")) -> BatchAnnotationResponse:
    """Annotate prompts from CSV text."""

    try:
        prompts = parse_csv_annotations(csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return await run_annotation_batch(prompts)


@app.post("/api/annotate/csv/validate")
async def validate_annotation_csv(csv_text: str = Body(..., media_type="text/csv")) -> dict:
    """Validate CSV input and return a lightweight preview summary."""

    try:
        prompts = parse_csv_annotations(csv_text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"valid_rows": len(prompts)}


async def run_annotation_batch(prompts: List[AnnotationRequest]) -> BatchAnnotationResponse:
    """Run a bounded-concurrency in-process annotation batch."""

    progress = BatchProgress(total=len(prompts))
    semaphore = asyncio.Semaphore(MAX_PROMPT_CONCURRENCY)

    async def run_one(prompt: AnnotationRequest) -> AnnotationResult | None:
        nonlocal progress
        async with semaphore:
            try:
                result = await annotate(prompt)
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
            except Exception:
                progress.failed += 1
                return None

    raw_results = await asyncio.gather(*(run_one(prompt) for prompt in prompts))
    results = [result for result in raw_results if result is not None]
    return BatchAnnotationResponse(results=results, progress=progress)


def all_stage1_votes_provider_failed(result: AnnotationResult) -> bool:
    """Return whether every Stage 1 vote is a provider/parse failure."""

    if not result.votes:
        return False
    return all(
        vote.parse_error is not None or "provider_failure" in vote.policy_triggers
        for vote in result.votes
    )


@app.get("/api/annotations", response_model=List[AnnotationResult])
async def list_annotations() -> List[AnnotationResult]:
    """List stored annotations."""

    return storage.list_annotations()


@app.get("/api/agreement", response_model=AgreementMetrics)
async def agreement() -> AgreementMetrics:
    """Report agreement among complete AI annotation panels."""

    return calculate_agreement(storage.list_annotations())


@app.get("/api/review-queue", response_model=List[AnnotationResult])
async def get_review_queue() -> List[AnnotationResult]:
    """List annotations requiring human review."""

    return storage.review_queue()


@app.post("/api/human-review", response_model=AnnotationResult)
async def human_review(request: HumanReviewRequest) -> AnnotationResult:
    """Store a human override."""

    try:
        return storage.add_human_review(request)
    except KeyError:
        raise HTTPException(status_code=404, detail="Annotation not found") from None


@app.get("/api/export-labels", response_model=List[ExportedLabel])
async def export_labels(include_prompt_text: bool = Query(default=False)) -> List[ExportedLabel]:
    """Export labels, preferring human overrides."""

    return storage.export_labels(include_prompt_text=include_prompt_text)


@app.get("/api/export-labels.csv")
async def export_labels_csv(include_prompt_text: bool = Query(default=False)) -> Response:
    """Export labels as CSV, preferring human overrides."""

    labels = storage.export_labels(include_prompt_text=include_prompt_text)
    csv_text = labels_to_csv(labels)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="labels.csv"'},
    )


def labels_to_csv(labels: List[ExportedLabel]) -> str:
    """Serialize exported labels to CSV."""

    output = io.StringIO()
    fieldnames = [
        "prompt_id",
        "prompt",
        "response",
        "label",
        "label_source",
        "confidence",
        "unsafe_category",
        "metadata",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for label in labels:
        writer.writerow(
            {
                "prompt_id": label.prompt_id,
                "prompt": label.prompt_text or "",
                "response": label.response_text or "",
                "label": label.label,
                "label_source": label.label_source,
                "confidence": "" if label.confidence is None else label.confidence,
                "unsafe_category": label.unsafe_category,
                "metadata": json.dumps(label.metadata, sort_keys=True),
            }
        )
    return output.getvalue()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
