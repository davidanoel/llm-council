"""FastAPI backend for cybersecurity prompt annotation."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import List

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import storage
from .council import run_council
from .csv_utils import parse_csv_annotations
from .evaluation import evaluate_predictions
from .model_provider import external_calls_disabled, get_model_provider_name
from .schemas import (
    AnnotationRequest,
    AnnotationResult,
    BatchAnnotationResponse,
    BatchAnnotationRequest,
    BatchProgress,
    EvaluationMetrics,
    EvaluationRequest,
    ExportedLabel,
    HumanReviewRequest,
    utc_now,
)


app = FastAPI(title="Cybersecurity Prompt Labelling API")
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
    votes, critiques, adjudication = await run_council(prompt_id, request.prompt_text, request.metadata)
    result = AnnotationResult(
        prompt_id=prompt_id,
        prompt_text=request.prompt_text,
        metadata=request.metadata,
        votes=votes,
        critiques=critiques,
        adjudication=adjudication,
        human_reviews=existing.human_reviews if existing else [],
        created_at=created_at,
        updated_at=utc_now(),
    )
    return storage.save_annotation(result)


@app.post("/api/annotate/batch", response_model=List[AnnotationResult])
async def annotate_batch_legacy(request: BatchAnnotationRequest) -> List[AnnotationResult]:
    """Deprecated compatibility endpoint shape."""

    response = await run_annotation_batch(request.prompts)
    return response.results


@app.post("/api/annotate/batch-with-progress", response_model=BatchAnnotationResponse)
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
                else:
                    progress.failed += 1
                return result
            except Exception:
                progress.failed += 1
                return None

    raw_results = await asyncio.gather(*(run_one(prompt) for prompt in prompts))
    results = [result for result in raw_results if result is not None]
    return BatchAnnotationResponse(results=results, progress=progress)


@app.get("/api/annotations", response_model=List[AnnotationResult])
async def list_annotations() -> List[AnnotationResult]:
    """List stored annotations."""

    return storage.list_annotations()


@app.get("/api/annotations/{prompt_id}", response_model=AnnotationResult)
async def get_annotation(prompt_id: str) -> AnnotationResult:
    """Get one stored annotation."""

    annotation = storage.load_annotation(prompt_id)
    if annotation is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return annotation


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


@app.post("/api/evaluate", response_model=EvaluationMetrics)
async def evaluate(request: EvaluationRequest) -> EvaluationMetrics:
    """Evaluate exported labels against supplied human-majority labels."""

    gold = {item.prompt_id: item.label for item in request.labels}
    return evaluate_predictions(storage.export_labels(), gold)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
