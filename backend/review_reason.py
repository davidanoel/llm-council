"""Review reason classification for human-review items."""

from __future__ import annotations

from collections import Counter

from .schemas import AnnotationResult, ModelVote, ReviewSuggestion


def classify_review_reason(annotation: AnnotationResult) -> ReviewSuggestion:
    """Return why an item needs review and any obvious suggested label."""

    decision_type = annotation.adjudication.decision_type if annotation.adjudication else None
    if decision_type != "human_review":
        return ReviewSuggestion(reason_type="none")

    failed_votes = [vote for vote in annotation.votes if vote_failed(vote)]
    valid_votes = [vote for vote in annotation.votes if not vote_failed(vote)]
    label_counts = Counter(vote.label for vote in valid_votes)
    suggested_label, suggested_category = suggested_from_votes(valid_votes)

    if failed_votes:
        return ReviewSuggestion(
            reason_type="provider_failure",
            suggested_label=suggested_label,
            suggested_unsafe_category=suggested_category,
        )
    if label_counts.get("needs_human_review", 0):
        return ReviewSuggestion(
            reason_type="abstention",
            suggested_label=suggested_label,
            suggested_unsafe_category=suggested_category,
        )
    if len({vote.label for vote in valid_votes}) > 1:
        return ReviewSuggestion(
            reason_type="disagreement",
            suggested_label=suggested_label,
            suggested_unsafe_category=suggested_category,
        )
    return ReviewSuggestion(reason_type="ambiguous")


def vote_failed(vote: ModelVote) -> bool:
    """Return whether a model vote failed due to provider or parse issues."""

    return vote.parse_error is not None or "provider_failure" in vote.policy_triggers


def suggested_from_votes(votes: list[ModelVote]) -> tuple[str | None, str]:
    """Suggest a label only when at least two valid model votes agree."""

    labels = [vote.label for vote in votes if vote.label in ("safe", "unsafe")]
    if len(labels) < 2:
        return None, "none"

    label, count = Counter(labels).most_common(1)[0]
    if count < 2:
        return None, "none"

    if label == "unsafe":
        categories = [
            vote.unsafe_category
            for vote in votes
            if vote.label == "unsafe" and vote.unsafe_category != "none"
        ]
        category = Counter(categories).most_common(1)[0][0] if categories else "other"
        return "unsafe", category
    return "safe", "none"
