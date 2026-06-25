from backend.review_reason import classify_review_reason
from backend.schemas import AnnotationResult, CouncilDecision, ModelVote, utc_now


def vote(model, label, parse_error=None):
    return ModelVote(
        prompt_id="p1",
        model_name=model,
        label=label,
        unsafe_category="none",
        confidence=0.0 if parse_error else 0.8,
        rationale="vote",
        policy_triggers=["provider_failure"] if parse_error else [],
        parse_error=parse_error,
    )


def annotation(votes):
    return AnnotationResult(
        prompt_id="p1",
        prompt_text="prompt",
        votes=votes,
        adjudication=CouncilDecision(
            prompt_id="p1",
            final_label="needs_human_review",
            unsafe_category="none",
            confidence=0.5,
            rationale="review",
            human_review_reason="review",
            decision_type="human_review",
        ),
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def test_review_reason_provider_failure():
    suggestion = classify_review_reason(
        annotation([
            vote("m1", "needs_human_review", parse_error="failed"),
            vote("m2", "safe"),
            vote("m3", "unsafe"),
        ])
    )

    assert suggestion.reason_type == "provider_failure"
    assert suggestion.suggested_label is None


def test_review_reason_abstention():
    suggestion = classify_review_reason(
        annotation([
            vote("m1", "safe"),
            vote("m2", "unsafe"),
            vote("m3", "needs_human_review"),
        ])
    )

    assert suggestion.reason_type == "abstention"


def test_review_reason_disagreement():
    suggestion = classify_review_reason(
        annotation([
            vote("m1", "safe"),
            vote("m2", "unsafe"),
            vote("m3", "unsafe"),
        ])
    )

    assert suggestion.reason_type == "disagreement"
    assert suggestion.suggested_label == "unsafe"
