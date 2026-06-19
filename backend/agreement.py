"""Agreement metrics for the three AI annotators."""

from __future__ import annotations

import csv
import io
from collections import Counter
from typing import List

from .schemas import AgreementMetrics, AnnotationResult, ExportAnalysis, ModelVote


LABELS = ("safe", "unsafe", "needs_human_review")
RATERS_PER_ITEM = 3


def calculate_agreement(annotations: List[AnnotationResult]) -> AgreementMetrics:
    """Calculate Fleiss' kappa over complete, successful AI vote panels."""

    complete = [
        annotation
        for annotation in annotations
        if len(annotation.votes) == RATERS_PER_ITEM
        and len({vote.model_name for vote in annotation.votes}) == RATERS_PER_ITEM
        and not any(vote.parse_error for vote in annotation.votes)
    ]
    total = len(annotations)
    if not complete:
        return AgreementMetrics(
            fleiss_kappa=None,
            observed_agreement=None,
            unanimous_rate=None,
            complete_items=0,
            excluded_items=total,
            coverage_rate=0.0,
        )

    category_totals = Counter()
    item_agreements = []
    unanimous = 0
    for annotation in complete:
        counts = Counter(vote.label for vote in annotation.votes)
        category_totals.update(counts)
        if max(counts.values()) == RATERS_PER_ITEM:
            unanimous += 1
        agreeing_pairs = sum(count * (count - 1) for count in counts.values())
        item_agreements.append(agreeing_pairs / (RATERS_PER_ITEM * (RATERS_PER_ITEM - 1)))

    observed = sum(item_agreements) / len(item_agreements)
    rating_count = len(complete) * RATERS_PER_ITEM
    expected = sum((category_totals[label] / rating_count) ** 2 for label in LABELS)
    kappa = None if expected == 1.0 else (observed - expected) / (1.0 - expected)

    return AgreementMetrics(
        fleiss_kappa=round(kappa, 4) if kappa is not None else None,
        observed_agreement=round(observed, 4),
        unanimous_rate=round(unanimous / len(complete), 4),
        complete_items=len(complete),
        excluded_items=total - len(complete),
        coverage_rate=round(len(complete) / total, 4) if total else 0.0,
    )


def analyze_export_csv(csv_text: str) -> ExportAnalysis:
    """Reconstruct metrics from a CSV created by the label export endpoint."""

    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"prompt_id", "label", "label_source", "vote_1_model", "vote_1_label"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("CSV must be a labels export containing model vote columns.")

    annotations = []
    final_counts = Counter()
    human_review_items = 0
    for row_number, row in enumerate(reader, start=1):
        prompt_id = (row.get("prompt_id") or "").strip() or f"row_{row_number}"
        votes = []
        for index in range(1, 4):
            model_name = (row.get(f"vote_{index}_model") or "").strip()
            if not model_name:
                continue
            votes.append(
                ModelVote(
                    prompt_id=prompt_id,
                    model_name=model_name,
                    label=(row.get(f"vote_{index}_label") or "").strip(),
                    confidence=float(row.get(f"vote_{index}_confidence") or 0),
                    unsafe_category=(row.get(f"vote_{index}_unsafe_category") or "").strip() or "none",
                    rationale=row.get(f"vote_{index}_rationale") or "",
                    parse_error=(row.get(f"vote_{index}_parse_error") or "").strip() or None,
                )
            )
        annotations.append(
            AnnotationResult(
                prompt_id=prompt_id,
                prompt_text=row.get("prompt") or "",
                response_text=(row.get("response") or "").strip() or None,
                votes=votes,
                created_at="",
                updated_at="",
            )
        )
        final_label = (row.get("label") or "").strip()
        if final_label not in LABELS:
            raise ValueError(f"Row {row_number} has an invalid final label.")
        final_counts[final_label] += 1
        if (row.get("label_source") or "").strip() == "human":
            human_review_items += 1

    return ExportAnalysis(
        agreement=calculate_agreement(annotations),
        total_items=len(annotations),
        safe_items=final_counts["safe"],
        unsafe_items=final_counts["unsafe"],
        unresolved_items=final_counts["needs_human_review"],
        human_review_items=human_review_items,
    )
