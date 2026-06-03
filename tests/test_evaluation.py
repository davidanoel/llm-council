from backend.evaluation import evaluate_predictions
from backend.schemas import ExportedLabel


def test_evaluation_metrics_ignore_abstentions_by_default():
    predictions = [
        ExportedLabel(prompt_id="p1", label="unsafe", label_source="council", unsafe_category="malware"),
        ExportedLabel(prompt_id="p2", label="safe", label_source="council"),
        ExportedLabel(prompt_id="p3", label="unsafe", label_source="council", unsafe_category="phishing"),
        ExportedLabel(prompt_id="p4", label="needs_human_review", label_source="council"),
    ]
    gold = {
        "p1": "unsafe",
        "p2": "safe",
        "p3": "safe",
        "p4": "unsafe",
    }

    metrics = evaluate_predictions(predictions, gold)

    assert metrics.confusion_matrix == {"tp": 1, "tn": 1, "fp": 1, "fn": 0}
    assert metrics.accuracy == 0.6667
    assert metrics.unsafe_precision == 0.5
    assert metrics.unsafe_recall == 1.0
    assert metrics.unsafe_f1 == 0.6667
    assert metrics.false_positive_rate == 0.5
    assert metrics.false_negative_rate == 0.0
    assert metrics.abstention_rate == 0.25
    assert metrics.coverage_rate == 0.75
