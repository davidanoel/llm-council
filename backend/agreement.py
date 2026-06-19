"""Agreement metrics for the three AI annotators."""

from __future__ import annotations

from collections import Counter
from typing import List

from .schemas import AgreementMetrics, AnnotationResult


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
