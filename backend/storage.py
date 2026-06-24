"""SQLite storage for annotation results."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import List, Optional

from .schemas import AnnotationResult, ExportedLabel, HumanReview, HumanReviewRequest, utc_now


DB_PATH = os.getenv("ANNOTATION_DB_PATH", "data/annotations.db")


def connect() -> sqlite3.Connection:
    """Open the local database and ensure its small schema exists."""

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS annotations (
            prompt_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            decision_type TEXT,
            final_label TEXT,
            has_human_review INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_annotations_created_at
            ON annotations(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_annotations_review_queue
            ON annotations(decision_type, has_human_review, created_at DESC);
        """
    )
    connection.commit()
    return connection


def upsert_annotation(
    connection: sqlite3.Connection,
    annotation: AnnotationResult,
) -> None:
    """Insert an annotation payload and its query fields."""

    values = (
        annotation.prompt_id,
        json.dumps(annotation.model_dump()),
        annotation.created_at,
        annotation.updated_at,
        annotation.adjudication.decision_type if annotation.adjudication else None,
        annotation.adjudication.final_label if annotation.adjudication else None,
        int(bool(annotation.human_reviews)),
    )
    connection.execute(
        """
        INSERT INTO annotations(
            prompt_id, payload, created_at, updated_at,
            decision_type, final_label, has_human_review
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(prompt_id) DO UPDATE SET
            payload = excluded.payload,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at,
            decision_type = excluded.decision_type,
            final_label = excluded.final_label,
            has_human_review = excluded.has_human_review
        """,
        values,
    )


def save_annotation(annotation: AnnotationResult) -> AnnotationResult:
    """Persist an annotation result."""

    annotation.updated_at = utc_now()
    with closing(connect()) as connection:
        upsert_annotation(connection, annotation)
        connection.commit()
    return annotation


def load_annotation(prompt_id: str) -> Optional[AnnotationResult]:
    """Load one annotation result."""

    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT payload FROM annotations WHERE prompt_id = ?",
            (prompt_id,),
        ).fetchone()
    return AnnotationResult(**json.loads(row["payload"])) if row else None


def list_annotations() -> List[AnnotationResult]:
    """List all annotation results sorted newest first."""

    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT payload FROM annotations ORDER BY created_at DESC"
        ).fetchall()
    return [AnnotationResult(**json.loads(row["payload"])) for row in rows]


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
            reviewed_at=utc_now(),
        )
    )
    return save_annotation(annotation)


def review_queue() -> List[AnnotationResult]:
    """Return unresolved annotations that need human review."""

    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT payload FROM annotations
            WHERE decision_type = 'human_review' AND has_human_review = 0
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [AnnotationResult(**json.loads(row["payload"])) for row in rows]


def clear_annotations() -> None:
    """Remove all stored annotations."""

    with closing(connect()) as connection:
        connection.execute("DELETE FROM annotations")
        connection.commit()


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
                response_text=annotation.response_text if include_prompt_text else None,
                metadata=annotation.metadata,
                votes=annotation.votes,
                created_at=annotation.created_at,
                updated_at=annotation.updated_at,
            )
        )
    return exported
