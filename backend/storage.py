"""Local JSON storage for annotation results."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from .schemas import AnnotationResult, ExportedLabel, HumanReview, HumanReviewRequest, utc_now


DATA_DIR = os.getenv("ANNOTATION_DATA_DIR", "data/annotations")


def ensure_data_dir() -> None:
    """Ensure annotation data directory exists."""

    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def annotation_path(prompt_id: str) -> str:
    """Return JSON path for a prompt annotation."""

    return os.path.join(DATA_DIR, f"{prompt_id}.json")


def save_annotation(annotation: AnnotationResult) -> AnnotationResult:
    """Persist an annotation result."""

    ensure_data_dir()
    annotation.updated_at = utc_now()
    with open(annotation_path(annotation.prompt_id), "w", encoding="utf-8") as handle:
        json.dump(annotation.model_dump(), handle, indent=2)
    return annotation


def load_annotation(prompt_id: str) -> Optional[AnnotationResult]:
    """Load one annotation result."""

    path = annotation_path(prompt_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return AnnotationResult(**json.load(handle))


def list_annotations() -> List[AnnotationResult]:
    """List all annotation results sorted newest first."""

    ensure_data_dir()
    results = []
    for filename in os.listdir(DATA_DIR):
        if filename.endswith(".json"):
            with open(os.path.join(DATA_DIR, filename), "r", encoding="utf-8") as handle:
                results.append(AnnotationResult(**json.load(handle)))
    results.sort(key=lambda item: item.created_at, reverse=True)
    return results


def add_human_review(request: HumanReviewRequest) -> AnnotationResult:
    """Append a human review to an annotation."""

    annotation = load_annotation(request.prompt_id)
    if annotation is None:
        raise KeyError(f"Annotation {request.prompt_id} not found")
    annotation.human_reviews.append(
        HumanReview(
            label=request.label,
            unsafe_category=request.unsafe_category,
            rationale=request.rationale,
            reviewer=request.reviewer,
            notes=request.notes,
            reviewed_at=utc_now(),
        )
    )
    return save_annotation(annotation)


def review_queue() -> List[AnnotationResult]:
    """Return annotations that need human review and lack a human review."""

    return [
        annotation for annotation in list_annotations()
        if annotation.adjudication
        and annotation.adjudication.decision_type == "human_review"
        and not annotation.human_reviews
    ]


def export_labels(include_prompt_text: bool = False) -> List[ExportedLabel]:
    """Export final labels, preferring latest human review."""

    exported = []
    for annotation in list_annotations():
        if annotation.human_reviews:
            review = annotation.human_reviews[-1]
            label = review.label
            source = "human"
            confidence = None
            unsafe_category = review.unsafe_category
        elif annotation.adjudication:
            label = annotation.adjudication.final_label
            source = "council"
            confidence = annotation.adjudication.confidence
            unsafe_category = annotation.adjudication.unsafe_category
        else:
            continue

        exported.append(
            ExportedLabel(
                prompt_id=annotation.prompt_id,
                label=label,
                label_source=source,
                confidence=confidence,
                unsafe_category=unsafe_category,
                prompt_text=annotation.prompt_text if include_prompt_text else None,
                metadata=annotation.metadata,
            )
        )
    return exported
