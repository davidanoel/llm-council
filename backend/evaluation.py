"""Evaluation metrics for exported prompt labels."""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from .schemas import EvaluationMetrics, ExportedLabel


def evaluate_predictions(predictions: List[ExportedLabel], gold_labels: Dict[str, str]) -> EvaluationMetrics:
    """Evaluate labels using unsafe as positive and safe as negative."""

    by_id = {prediction.prompt_id: prediction for prediction in predictions}
    tp = tn = fp = fn = abstained = covered = 0

    for prompt_id, gold in gold_labels.items():
        prediction = by_id.get(prompt_id)
        if prediction is None or prediction.label == "needs_human_review":
            abstained += 1
            continue

        covered += 1
        pred_positive = prediction.label == "unsafe"
        gold_positive = gold == "unsafe"

        if pred_positive and gold_positive:
            tp += 1
        elif pred_positive and not gold_positive:
            fp += 1
        elif not pred_positive and gold_positive:
            fn += 1
        else:
            tn += 1

    total = len(gold_labels)
    accuracy = safe_divide(tp + tn, covered)
    precision = safe_divide(tp, tp + fp)
    recall = safe_divide(tp, tp + fn)
    f1 = safe_divide(2 * precision * recall, precision + recall) if precision is not None and recall is not None else None
    fpr = safe_divide(fp, fp + tn)
    fnr = safe_divide(fn, fn + tp)
    mcc = calculate_mcc(tp, tn, fp, fn)

    return EvaluationMetrics(
        confusion_matrix={"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        accuracy=accuracy,
        unsafe_precision=precision,
        unsafe_recall=recall,
        unsafe_f1=f1,
        mcc=mcc,
        false_positive_rate=fpr,
        false_negative_rate=fnr,
        abstention_rate=safe_divide(abstained, total) or 0.0,
        coverage_rate=safe_divide(covered, total) or 0.0,
        total=total,
        covered=covered,
        abstained=abstained,
    )


def safe_divide(numerator: float, denominator: float) -> Optional[float]:
    """Divide with None for undefined metrics."""

    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def calculate_mcc(tp: int, tn: int, fp: int, fn: int) -> Optional[float]:
    """Calculate Matthews correlation coefficient."""

    denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    if denominator == 0:
        return None
    return round(((tp * tn) - (fp * fn)) / denominator, 4)
