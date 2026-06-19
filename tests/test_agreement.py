from backend.agreement import calculate_agreement
from backend.schemas import AnnotationResult, ModelVote, utc_now


def annotation(prompt_id, labels, failed_index=None):
    votes = []
    for index, label in enumerate(labels):
        failed = index == failed_index
        votes.append(
            ModelVote(
                prompt_id=prompt_id,
                model_name=f"model-{index}",
                label="needs_human_review" if failed else label,
                confidence=0.0 if failed else 0.9,
                rationale="vote",
                policy_triggers=["provider_failure"] if failed else [],
                parse_error="failed" if failed else None,
            )
        )
    return AnnotationResult(
        prompt_id=prompt_id,
        prompt_text="prompt",
        votes=votes,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def test_fleiss_kappa_reports_perfect_agreement():
    metrics = calculate_agreement(
        [
            annotation("p1", ["safe", "safe", "safe"]),
            annotation("p2", ["unsafe", "unsafe", "unsafe"]),
        ]
    )

    assert metrics.fleiss_kappa == 1.0
    assert metrics.observed_agreement == 1.0
    assert metrics.unanimous_rate == 1.0
    assert metrics.coverage_rate == 1.0


def test_fleiss_kappa_excludes_provider_failures_and_reports_coverage():
    metrics = calculate_agreement(
        [
            annotation("p1", ["safe", "safe", "unsafe"]),
            annotation("p2", ["safe", "safe", "safe"], failed_index=2),
        ]
    )

    assert metrics.complete_items == 1
    assert metrics.excluded_items == 1
    assert metrics.coverage_rate == 0.5
    assert metrics.observed_agreement == 0.3333
