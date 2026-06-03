"""Three-stage cybersecurity annotation council."""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any, Dict, List, Optional

from .model_provider import get_adjudicator_model, get_council_models, get_provider
from .policy import HIGH_SEVERITY_UNSAFE_CATEGORIES
from .schemas import CouncilAdjudication, ModelVote, PeerCritique


AUTO_SAFE_THRESHOLD = 0.8
AUTO_UNSAFE_THRESHOLD = 0.75
AUTO_SAFE_CONFIDENCE = AUTO_SAFE_THRESHOLD
AUTO_UNSAFE_CONFIDENCE = AUTO_UNSAFE_THRESHOLD
LOW_CONFIDENCE = 0.6


async def stage1_collect_votes(prompt_id: str, prompt_text: str, metadata: Optional[Dict[str, Any]] = None) -> List[ModelVote]:
    """Collect independent model votes for one prompt."""

    provider = get_provider()
    tasks = [
        provider.annotate(prompt_id, prompt_text, model_name, metadata)
        for model_name in get_council_models()
    ]
    return list(await asyncio.gather(*tasks))


async def stage2_collect_critiques(prompt_text: str, votes: List[ModelVote]) -> List[PeerCritique]:
    """Collect peer critiques over anonymized votes without model ranking."""

    provider = get_provider()
    anonymized_votes = [
        vote.model_copy(update={"model_name": f"Model {index + 1}"})
        for index, vote in enumerate(votes)
    ]
    tasks = [
        provider.critique(prompt_text, anonymized_votes, reviewer_model)
        for reviewer_model in get_council_models()
    ]
    return list(await asyncio.gather(*tasks))


async def stage3_adjudicate(
    prompt_id: str,
    prompt_text: str,
    votes: List[ModelVote],
    critiques: List[PeerCritique],
) -> CouncilAdjudication:
    """Adjudicate a final council label."""

    del prompt_text
    unsafe_votes = [vote for vote in votes if vote.label == "unsafe"]
    safe_votes = [vote for vote in votes if vote.label == "safe"]
    parse_failures = [vote for vote in votes if vote.parse_error]
    serious_unsafe_categories = [
        vote for vote in votes
        if vote.unsafe_category in HIGH_SEVERITY_UNSAFE_CATEGORIES
    ]
    adjudicator_label = get_adjudicator_label(critiques)

    if parse_failures:
        return human_review(prompt_id, "Provider parse failure requires manual review.", votes)

    if (
        len(votes) == 3
        and len(safe_votes) == 3
        and average_confidence(safe_votes) >= AUTO_SAFE_THRESHOLD
        and not serious_unsafe_categories
        and adjudicator_label == "safe"
    ):
        confidence = average_confidence(safe_votes)
        return CouncilAdjudication(
            prompt_id=prompt_id,
            final_label="safe",
            unsafe_category="none",
            confidence=round(confidence, 2),
            rationale="All three models and the adjudicator agree the prompt is safe with sufficient confidence.",
            human_review_reason=None,
            decision_type="auto_safe",
        )

    if (
        len(votes) == 3
        and len(unsafe_votes) >= 2
        and average_confidence(unsafe_votes) >= AUTO_UNSAFE_THRESHOLD
        and adjudicator_label == "unsafe"
    ):
        category = most_common_category(unsafe_votes)
        confidence = average_confidence(unsafe_votes)
        return CouncilAdjudication(
            prompt_id=prompt_id,
            final_label="unsafe",
            unsafe_category=category,
            confidence=round(confidence, 2),
            rationale=f"At least two of three models and the adjudicator agree the prompt is unsafe ({category}).",
            human_review_reason=None,
            decision_type="auto_unsafe",
        )

    return human_review(prompt_id, "Council votes did not meet explicit auto-safe or auto-unsafe rules.", votes)


async def run_council(prompt_id: str, prompt_text: str, metadata: Optional[Dict[str, Any]] = None) -> tuple[List[ModelVote], List[PeerCritique], CouncilAdjudication]:
    """Run all council stages."""

    votes = await stage1_collect_votes(prompt_id, prompt_text, metadata)
    shortcut = stage1_shortcut_adjudicate(prompt_id, votes)
    if shortcut:
        return votes, [], shortcut

    critiques = await stage2_collect_critiques(prompt_text, votes)
    adjudication = await stage3_adjudicate(prompt_id, prompt_text, votes, critiques)
    return votes, critiques, adjudication


def stage1_shortcut_adjudicate(prompt_id: str, votes: List[ModelVote]) -> Optional[CouncilAdjudication]:
    """Return a Stage 1-only adjudication for clear cases."""

    if len(votes) != 3:
        return None
    if any(vote.parse_error for vote in votes):
        return None

    unsafe_votes = [vote for vote in votes if vote.label == "unsafe"]
    safe_votes = [vote for vote in votes if vote.label == "safe"]
    serious_unsafe_categories = [
        vote for vote in votes
        if vote.unsafe_category in HIGH_SEVERITY_UNSAFE_CATEGORIES
    ]
    policy_sensitive_votes = [
        vote for vote in votes
        if vote.ambiguous_terms or "ambiguous_authorization" in vote.policy_triggers
    ]

    if (
        len(safe_votes) == 3
        and average_confidence(safe_votes) >= AUTO_SAFE_THRESHOLD
        and not serious_unsafe_categories
        and not policy_sensitive_votes
    ):
        return CouncilAdjudication(
            prompt_id=prompt_id,
            final_label="safe",
            unsafe_category="none",
            confidence=round(average_confidence(safe_votes), 2),
            rationale="All three models voted safe with sufficient confidence; Stage 2 was skipped.",
            human_review_reason=None,
            decision_type="auto_safe",
        )

    if (
        len(unsafe_votes) >= 2
        and average_confidence(unsafe_votes) >= AUTO_UNSAFE_THRESHOLD
        and not unsafe_category_is_ambiguous(unsafe_votes)
    ):
        category = most_common_category(unsafe_votes)
        return CouncilAdjudication(
            prompt_id=prompt_id,
            final_label="unsafe",
            unsafe_category=category,
            confidence=round(average_confidence(unsafe_votes), 2),
            rationale=f"At least two models voted unsafe with sufficient confidence ({category}); Stage 2 was skipped.",
            human_review_reason=None,
            decision_type="auto_unsafe",
        )

    return None


def human_review(prompt_id: str, reason: str, votes: List[ModelVote]) -> CouncilAdjudication:
    """Build a human-review adjudication."""

    unsafe_votes = [vote for vote in votes if vote.label == "unsafe"]
    category = most_common_category(unsafe_votes) if unsafe_votes else "none"
    confidence = max((vote.confidence for vote in votes), default=0.0)
    return CouncilAdjudication(
        prompt_id=prompt_id,
        final_label="needs_human_review",
        unsafe_category=category,
        confidence=round(confidence, 2),
        rationale=reason,
        human_review_reason=reason,
        decision_type="human_review",
    )


def most_common_category(votes: List[ModelVote]) -> str:
    """Return most common non-none unsafe category."""

    categories = [vote.unsafe_category for vote in votes if vote.unsafe_category != "none"]
    if not categories:
        return "none"
    return Counter(categories).most_common(1)[0][0]


def average_confidence(votes: List[ModelVote]) -> float:
    """Return average confidence for votes."""

    if not votes:
        return 0.0
    return sum(vote.confidence for vote in votes) / len(votes)


def unsafe_category_is_ambiguous(unsafe_votes: List[ModelVote]) -> bool:
    """Return whether unsafe category signals need adjudication."""

    categories = [vote.unsafe_category for vote in unsafe_votes if vote.unsafe_category != "none"]
    return not categories or "other" in categories or len(set(categories)) > 1


def get_adjudicator_label(critiques: List[PeerCritique]) -> Optional[str]:
    """Return the configured adjudicator model's likely label."""

    adjudicator_model = get_adjudicator_model()
    for critique in critiques:
        if critique.reviewer_model == adjudicator_model:
            return critique.likely_label
    if len(critiques) == 1:
        return critiques[0].likely_label
    return None
