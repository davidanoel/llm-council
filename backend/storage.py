"""SQLite storage for annotation runs and results."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schemas import (
    AnnotationResult,
    CouncilDecision,
    ExportedLabel,
    HumanReview,
    HumanReviewRequest,
    ModelVote,
    RunSummary,
    utc_now,
)
from .review_reason import classify_review_reason, vote_failed


DB_PATH = os.getenv("ANNOTATION_DB_PATH", "data/annotations.db")
POLICY_VERSION = "cyber-policy-v1"
DECISION_RULE_VERSION = "majority-v1"


def connect() -> sqlite3.Connection:
    """Open the local database and ensure its schema exists."""

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_filename TEXT,
            task_type TEXT NOT NULL DEFAULT 'prompt_classification',
            policy_version TEXT NOT NULL,
            model_config_json TEXT NOT NULL,
            decision_rule_version TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS items (
            item_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            prompt_id TEXT NOT NULL,
            prompt_text TEXT NOT NULL,
            response_text TEXT,
            metadata_json TEXT NOT NULL,
            row_number INTEGER,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(run_id, prompt_id)
        );

        CREATE TABLE IF NOT EXISTS model_votes (
            item_id TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
            vote_index INTEGER NOT NULL,
            model_name TEXT NOT NULL,
            label TEXT NOT NULL,
            unsafe_category TEXT NOT NULL,
            confidence REAL NOT NULL,
            rationale TEXT NOT NULL,
            policy_triggers_json TEXT NOT NULL,
            ambiguous_terms_json TEXT NOT NULL,
            parse_error TEXT,
            PRIMARY KEY(item_id, vote_index)
        );

        CREATE TABLE IF NOT EXISTS decisions (
            item_id TEXT PRIMARY KEY REFERENCES items(item_id) ON DELETE CASCADE,
            final_label TEXT NOT NULL,
            unsafe_category TEXT NOT NULL,
            confidence REAL NOT NULL,
            rationale TEXT NOT NULL,
            human_review_reason TEXT,
            decision_type TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS human_reviews (
            review_id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            unsafe_category TEXT NOT NULL,
            rationale TEXT,
            reviewer TEXT NOT NULL,
            reviewed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_runs_created_at
            ON runs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_items_run
            ON items(run_id, row_number, created_at);
        CREATE INDEX IF NOT EXISTS idx_items_prompt
            ON items(prompt_id);
        CREATE INDEX IF NOT EXISTS idx_decisions_type
            ON decisions(decision_type);
        CREATE INDEX IF NOT EXISTS idx_reviews_item
            ON human_reviews(item_id, reviewed_at);
        """
    )
    ensure_column(connection, "runs", "task_type", "TEXT NOT NULL DEFAULT 'prompt_classification'")
    ensure_column(connection, "items", "error_message", "TEXT")
    connection.commit()
    return connection


def ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """Add a column when opening an older local SQLite file."""

    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def create_run(
    name: Optional[str] = None,
    source_filename: Optional[str] = None,
    task_type: str = "prompt_classification",
    model_config: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
) -> RunSummary:
    """Create an annotation run."""

    now = utc_now()
    run = RunSummary(
        run_id=run_id or str(uuid.uuid4()),
        name=name or "Annotation run",
        source_filename=source_filename,
        task_type=task_type,
        policy_version=POLICY_VERSION,
        model_config_json=model_config or {},
        decision_rule_version=DECISION_RULE_VERSION,
        status="running",
        created_at=now,
        completed_at=None,
    )
    with closing(connect()) as connection:
        upsert_run(connection, run)
        connection.commit()
    return run


def upsert_run(connection: sqlite3.Connection, run: RunSummary) -> None:
    """Insert or update a run row."""

    connection.execute(
        """
        INSERT INTO runs(
            run_id, name, source_filename, task_type, policy_version, model_config_json,
            decision_rule_version, status, created_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            name = excluded.name,
            source_filename = excluded.source_filename,
            task_type = excluded.task_type,
            policy_version = excluded.policy_version,
            model_config_json = excluded.model_config_json,
            decision_rule_version = excluded.decision_rule_version,
            status = excluded.status,
            created_at = excluded.created_at,
            completed_at = excluded.completed_at
        """,
        (
            run.run_id,
            run.name,
            run.source_filename,
            run.task_type,
            run.policy_version,
            json.dumps(run.model_config_json, sort_keys=True),
            run.decision_rule_version,
            run.status,
            run.created_at,
            run.completed_at,
        ),
    )


def complete_run(run_id: str, status: str = "completed") -> RunSummary:
    """Mark a run as completed or failed."""

    with closing(connect()) as connection:
        connection.execute(
            "UPDATE runs SET status = ?, completed_at = ? WHERE run_id = ?",
            (status, utc_now(), run_id),
        )
        connection.commit()
    run = load_run(run_id)
    if run is None:
        raise KeyError(f"Run {run_id} not found")
    return run


def set_run_status(run_id: str, status: str, completed_at: str | None = None) -> RunSummary:
    """Set run status without changing its items."""

    with closing(connect()) as connection:
        connection.execute(
            "UPDATE runs SET status = ?, completed_at = ? WHERE run_id = ?",
            (status, completed_at, run_id),
        )
        connection.commit()
    run = load_run(run_id)
    if run is None:
        raise KeyError(f"Run {run_id} not found")
    return run


def rename_run(run_id: str, name: str) -> RunSummary:
    """Rename one run."""

    with closing(connect()) as connection:
        cursor = connection.execute(
            "UPDATE runs SET name = ? WHERE run_id = ?",
            (name.strip(), run_id),
        )
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError(f"Run {run_id} not found")
    run = load_run(run_id)
    if run is None:
        raise KeyError(f"Run {run_id} not found")
    return run


def load_run(run_id: str) -> Optional[RunSummary]:
    """Load one run summary."""

    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return build_run_summary(connection, row) if row else None


def list_runs() -> List[RunSummary]:
    """List runs sorted newest first."""

    with closing(connect()) as connection:
        rows = connection.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        return [build_run_summary(connection, row) for row in rows]


def build_run_summary(connection: sqlite3.Connection, row: sqlite3.Row) -> RunSummary:
    """Build a run summary with item and outcome counts."""

    counts = connection.execute(
        """
        SELECT
            COUNT(i.item_id) AS total_items,
            COUNT(d.item_id) AS completed_items,
            SUM(CASE WHEN i.error_message IS NOT NULL AND d.item_id IS NULL THEN 1 ELSE 0 END) AS failed_items,
            SUM(CASE WHEN d.item_id IS NULL AND NOT EXISTS (
                SELECT 1 FROM human_reviews hr WHERE hr.item_id = i.item_id
            ) THEN 1 ELSE 0 END) AS resumable_items,
            SUM(CASE WHEN d.decision_type = 'auto_safe' THEN 1 ELSE 0 END) AS auto_safe,
            SUM(CASE WHEN d.decision_type = 'auto_unsafe' THEN 1 ELSE 0 END) AS auto_unsafe,
            SUM(CASE WHEN d.decision_type = 'human_review' THEN 1 ELSE 0 END) AS human_review
        FROM items i
        LEFT JOIN decisions d ON d.item_id = i.item_id
        WHERE i.run_id = ?
        """,
        (row["run_id"],),
    ).fetchone()
    annotations = [build_annotation(connection, row["item_id"]) for row in connection.execute(
        "SELECT item_id FROM items WHERE run_id = ?",
        (row["run_id"],),
    ).fetchall()]
    reason_counts = {
        "provider_failure": sum(item.review_reason_type == "provider_failure" for item in annotations),
        "disagreement": sum(item.review_reason_type == "disagreement" for item in annotations),
        "abstention": sum(item.review_reason_type == "abstention" for item in annotations),
        "ambiguous": sum(item.review_reason_type == "ambiguous" for item in annotations),
    }
    return RunSummary(
        run_id=row["run_id"],
        name=row["name"],
        source_filename=row["source_filename"],
        task_type=row["task_type"],
        policy_version=row["policy_version"],
        model_config_json=json.loads(row["model_config_json"]),
        decision_rule_version=row["decision_rule_version"],
        status=row["status"],
        total_items=counts["total_items"] or 0,
        completed_items=counts["completed_items"] or 0,
        auto_safe=counts["auto_safe"] or 0,
        auto_unsafe=counts["auto_unsafe"] or 0,
        human_review=counts["human_review"] or 0,
        provider_failed=reason_counts["provider_failure"],
        disagreement=reason_counts["disagreement"],
        abstention=reason_counts["abstention"],
        ambiguous=reason_counts["ambiguous"],
        failed_items=counts["failed_items"] or 0,
        resumable_items=counts["resumable_items"] or 0,
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


def save_annotation(
    annotation: AnnotationResult,
    run_id: str,
    row_number: Optional[int] = None,
) -> AnnotationResult:
    """Persist an annotation result."""

    target_run_id = run_id or annotation.run_id
    if not target_run_id:
        raise ValueError("run_id is required")
    if load_run(target_run_id) is None:
        raise KeyError(f"Run {target_run_id} not found")

    annotation.run_id = target_run_id
    if row_number is not None:
        annotation.row_number = row_number
    if not annotation.item_id:
        annotation.item_id = item_id_for(target_run_id, annotation.prompt_id)
    annotation.updated_at = utc_now()

    with closing(connect()) as connection:
        upsert_annotation(connection, annotation)
        connection.commit()
    return annotation


def upsert_annotation(connection: sqlite3.Connection, annotation: AnnotationResult) -> None:
    """Insert or update an annotation and its child rows."""

    connection.execute(
        """
        INSERT INTO items(
            item_id, run_id, prompt_id, prompt_text, response_text,
            metadata_json, row_number, error_message, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, prompt_id) DO UPDATE SET
            item_id = excluded.item_id,
            prompt_text = excluded.prompt_text,
            response_text = excluded.response_text,
            metadata_json = excluded.metadata_json,
            row_number = excluded.row_number,
            error_message = excluded.error_message,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at
        """,
        (
            annotation.item_id,
            annotation.run_id,
            annotation.prompt_id,
            annotation.prompt_text,
            annotation.response_text,
            json.dumps(annotation.metadata, sort_keys=True),
            annotation.row_number,
            annotation.error_message,
            annotation.created_at,
            annotation.updated_at,
        ),
    )
    connection.execute("DELETE FROM model_votes WHERE item_id = ?", (annotation.item_id,))
    for index, vote in enumerate(annotation.votes, start=1):
        connection.execute(
            """
            INSERT INTO model_votes(
                item_id, vote_index, model_name, label, unsafe_category,
                confidence, rationale, policy_triggers_json,
                ambiguous_terms_json, parse_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                annotation.item_id,
                index,
                vote.model_name,
                vote.label,
                vote.unsafe_category,
                vote.confidence,
                vote.rationale,
                json.dumps(vote.policy_triggers),
                json.dumps(vote.ambiguous_terms),
                vote.parse_error,
            ),
        )

    connection.execute("DELETE FROM decisions WHERE item_id = ?", (annotation.item_id,))
    if annotation.adjudication:
        decision = annotation.adjudication
        connection.execute(
            """
            INSERT INTO decisions(
                item_id, final_label, unsafe_category, confidence, rationale,
                human_review_reason, decision_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                annotation.item_id,
                decision.final_label,
                decision.unsafe_category,
                decision.confidence,
                decision.rationale,
                decision.human_review_reason,
                decision.decision_type,
            ),
        )


def item_id_for(run_id: str, prompt_id: str) -> str:
    """Build a stable item id inside a run."""

    return f"{run_id}:{prompt_id}"


def load_annotation(prompt_id: str, run_id: str) -> Optional[AnnotationResult]:
    """Load one annotation result."""

    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT item_id FROM items WHERE run_id = ? AND prompt_id = ?",
            (run_id, prompt_id),
        ).fetchone()
        return build_annotation(connection, row["item_id"]) if row else None


def load_annotation_by_item(item_id: str) -> Optional[AnnotationResult]:
    """Load one annotation by item id."""

    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT item_id FROM items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        return build_annotation(connection, item_id) if row else None


def list_annotations(run_id: str) -> List[AnnotationResult]:
    """List annotation results for one run."""

    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT item_id FROM items
            WHERE run_id = ?
            ORDER BY COALESCE(row_number, 999999999), created_at
            """,
            (run_id,),
        ).fetchall()
        return [build_annotation(connection, row["item_id"]) for row in rows]


def list_retryable_annotations(run_id: str) -> List[AnnotationResult]:
    """List non-reviewed items that have one or more provider/parse failures."""

    return [
        annotation
        for annotation in list_annotations(run_id)
        if not annotation.human_reviews
        and any(vote_failed(vote) for vote in annotation.votes)
    ]


def list_resumable_annotations(run_id: str) -> List[AnnotationResult]:
    """List non-reviewed items that do not have a final decision."""

    return [
        annotation
        for annotation in list_annotations(run_id)
        if annotation.adjudication is None and not annotation.human_reviews
    ]


def build_annotation(connection: sqlite3.Connection, item_id: str) -> AnnotationResult:
    """Build the nested API shape for one item."""

    item = connection.execute(
        "SELECT * FROM items WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    if item is None:
        raise KeyError(f"Item {item_id} not found")

    votes = [
        ModelVote(
            prompt_id=item["prompt_id"],
            model_name=row["model_name"],
            label=row["label"],
            unsafe_category=row["unsafe_category"],
            confidence=row["confidence"],
            rationale=row["rationale"],
            policy_triggers=json.loads(row["policy_triggers_json"]),
            ambiguous_terms=json.loads(row["ambiguous_terms_json"]),
            parse_error=row["parse_error"],
        )
        for row in connection.execute(
            "SELECT * FROM model_votes WHERE item_id = ? ORDER BY vote_index",
            (item_id,),
        ).fetchall()
    ]
    decision_row = connection.execute(
        "SELECT * FROM decisions WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    adjudication = (
        CouncilDecision(
            prompt_id=item["prompt_id"],
            final_label=decision_row["final_label"],
            unsafe_category=decision_row["unsafe_category"],
            confidence=decision_row["confidence"],
            rationale=decision_row["rationale"],
            human_review_reason=decision_row["human_review_reason"],
            decision_type=decision_row["decision_type"],
        )
        if decision_row
        else None
    )
    reviews = [
        HumanReview(
            label=row["label"],
            unsafe_category=row["unsafe_category"],
            rationale=row["rationale"],
            reviewer=row["reviewer"],
            reviewed_at=row["reviewed_at"],
        )
        for row in connection.execute(
            "SELECT * FROM human_reviews WHERE item_id = ? ORDER BY reviewed_at",
            (item_id,),
        ).fetchall()
    ]
    annotation = AnnotationResult(
        item_id=item["item_id"],
        run_id=item["run_id"],
        prompt_id=item["prompt_id"],
        prompt_text=item["prompt_text"],
        response_text=item["response_text"],
        metadata=json.loads(item["metadata_json"]),
        row_number=item["row_number"],
        error_message=item["error_message"],
        votes=votes,
        adjudication=adjudication,
        human_reviews=reviews,
        created_at=item["created_at"],
        updated_at=item["updated_at"],
    )
    suggestion = classify_review_reason(annotation)
    annotation.review_reason_type = suggestion.reason_type
    annotation.suggested_label = suggestion.suggested_label
    annotation.suggested_unsafe_category = suggestion.suggested_unsafe_category
    return annotation


def add_human_review(request: HumanReviewRequest) -> AnnotationResult:
    """Append a human review to an annotation."""

    annotation = load_annotation(request.prompt_id, run_id=request.run_id)
    if annotation is None or annotation.item_id is None:
        raise KeyError(f"Annotation {request.prompt_id} not found")

    with closing(connect()) as connection:
        connection.execute(
            """
            INSERT INTO human_reviews(
                review_id, item_id, label, unsafe_category, rationale, reviewer, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                annotation.item_id,
                request.label,
                request.unsafe_category,
                request.rationale,
                request.reviewer,
                utc_now(),
            ),
        )
        connection.execute(
            "UPDATE items SET updated_at = ? WHERE item_id = ?",
            (utc_now(), annotation.item_id),
        )
        connection.commit()
    return load_annotation_by_item(annotation.item_id)  # type: ignore[return-value]


def review_queue(run_id: str) -> List[AnnotationResult]:
    """Return unresolved annotations that need human review."""

    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT i.item_id FROM items i
            JOIN decisions d ON d.item_id = i.item_id
            WHERE i.run_id = ?
              AND d.decision_type = 'human_review'
              AND NOT EXISTS (
                  SELECT 1 FROM human_reviews hr WHERE hr.item_id = i.item_id
              )
            ORDER BY COALESCE(i.row_number, 999999999), i.created_at
            """,
            (run_id,),
        ).fetchall()
        return [build_annotation(connection, row["item_id"]) for row in rows]


def delete_run(run_id: str) -> bool:
    """Delete one run and its annotations."""

    with closing(connect()) as connection:
        cursor = connection.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        connection.commit()
    return cursor.rowcount > 0


def delete_annotation(prompt_id: str, run_id: str) -> bool:
    """Delete one stored annotation by prompt id."""

    with closing(connect()) as connection:
        cursor = connection.execute(
            "DELETE FROM items WHERE run_id = ? AND prompt_id = ?",
            (run_id, prompt_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def export_labels(
    include_prompt_text: bool = False,
    run_id: str = "",
) -> List[ExportedLabel]:
    """Export final labels, preferring latest human review."""

    exported = []
    run = load_run(run_id)
    if run is None:
        raise KeyError(f"Run {run_id} not found")
    for annotation in list_annotations(run_id=run_id):
        if annotation.human_reviews:
            review = annotation.human_reviews[-1]
            label = review.label
            source = "human"
            confidence = None
            unsafe_category = review.unsafe_category
            human_review_rationale = review.rationale
        elif annotation.adjudication:
            label = annotation.adjudication.final_label
            source = "council"
            confidence = annotation.adjudication.confidence
            unsafe_category = annotation.adjudication.unsafe_category
            human_review_rationale = None
        else:
            continue

        exported.append(
            ExportedLabel(
                run_id=annotation.run_id or run_id,
                run_name=run.name,
                task_type=run.task_type,
                row_number=annotation.row_number,
                prompt_id=annotation.prompt_id,
                label=label,
                label_source=source,
                decision_type=annotation.adjudication.decision_type if annotation.adjudication else "human_review",
                review_reason_type=annotation.review_reason_type,
                confidence=confidence,
                unsafe_category=unsafe_category,
                human_review_rationale=human_review_rationale,
                prompt_text=annotation.prompt_text if include_prompt_text else None,
                response_text=annotation.response_text if include_prompt_text else None,
                metadata=annotation.metadata,
                votes=annotation.votes,
                created_at=annotation.created_at,
                updated_at=annotation.updated_at,
            )
        )
    return exported
