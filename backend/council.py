"""Independent-model voting and deterministic annotation aggregation."""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any, Dict, List, Optional

from .model_provider import get_council_models, get_provider
from .policy import HIGH_SEVERITY_UNSAFE_CATEGORIES
from .schemas import CouncilDecision, ModelVote


AUTO_SAFE_THRESHOLD = 0.8
AUTO_UNSAFE_THRESHOLD = 0.75


async def collect_votes(
    prompt_id: str,
    prompt_text: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[ModelVote]:
    """Collect independent votes from every configured annotator."""

    provider = get_provider()
    tasks = [
        provider.annotate(prompt_id, prompt_text, model_name, metadata)
        for model_name in get_council_models()
    ]
    return list(await asyncio.gather(*tasks))


def aggregate_votes(prompt_id: str, votes: List[ModelVote]) -> CouncilDecision:
    """Apply asymmetric deterministic rules to independent model votes."""

    if len(votes) != 3:
        return human_review(prompt_id, "Expected three independent model votes.", votes)

    if any(vote.parse_error for vote in votes):
        return human_review(prompt_id, "One or more model provider calls failed.", votes)

    safe_votes = [vote for vote in votes if vote.label == "safe"]
    unsafe_votes = [vote for vote in votes if vote.label == "unsafe"]
    serious_unsafe_signal = any(
        vote.unsafe_category in HIGH_SEVERITY_UNSAFE_CATEGORIES
        for vote in votes
    )
    policy_sensitive_signal = any(
        vote.ambiguous_terms or "ambiguous_authorization" in vote.policy_triggers
        for vote in votes
    )

    if (
        len(safe_votes) == 3
        and average_confidence(safe_votes) >= AUTO_SAFE_THRESHOLD
        and not serious_unsafe_signal
        and not policy_sensitive_signal
    ):
        return CouncilDecision(
            prompt_id=prompt_id,
            final_label="safe",
            unsafe_category="none",
            confidence=round(average_confidence(safe_votes), 2),
            rationale="All three independent annotators voted safe with sufficient confidence.",
            human_review_reason=None,
            decision_type="auto_safe",
        )

    if (
        len(unsafe_votes) >= 2
        and average_confidence(unsafe_votes) >= AUTO_UNSAFE_THRESHOLD
        and not unsafe_category_is_ambiguous(unsafe_votes)
    ):
        category = most_common_category(unsafe_votes)
        return CouncilDecision(
            prompt_id=prompt_id,
            final_label="unsafe",
            unsafe_category=category,
            confidence=round(average_confidence(unsafe_votes), 2),
            rationale=f"At least two independent annotators voted unsafe with sufficient confidence ({category}).",
            human_review_reason=None,
            decision_type="auto_unsafe",
        )

    return human_review(
        prompt_id,
        "Independent votes did not meet the auto-safe or auto-unsafe rules.",
        votes,
    )


async def run_council(
    prompt_id: str,
    prompt_text: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> tuple[List[ModelVote], CouncilDecision]:
    """Collect independent votes and aggregate them deterministically."""

    votes = await collect_votes(prompt_id, prompt_text, metadata)
    return votes, aggregate_votes(prompt_id, votes)


def human_review(prompt_id: str, reason: str, votes: List[ModelVote]) -> CouncilDecision:
    """Build a human-review decision."""

    unsafe_votes = [vote for vote in votes if vote.label == "unsafe"]
    return CouncilDecision(
        prompt_id=prompt_id,
        final_label="needs_human_review",
        unsafe_category=most_common_category(unsafe_votes) if unsafe_votes else "none",
        confidence=round(max((vote.confidence for vote in votes), default=0.0), 2),
        rationale=reason,
        human_review_reason=reason,
        decision_type="human_review",
    )


def most_common_category(votes: List[ModelVote]) -> str:
    """Return the most common non-none unsafe category."""

    categories = [vote.unsafe_category for vote in votes if vote.unsafe_category != "none"]
    return Counter(categories).most_common(1)[0][0] if categories else "none"


def average_confidence(votes: List[ModelVote]) -> float:
    """Return average self-reported confidence for votes."""

    return sum(vote.confidence for vote in votes) / len(votes) if votes else 0.0


def unsafe_category_is_ambiguous(unsafe_votes: List[ModelVote]) -> bool:
    """Return whether unsafe category signals need human adjudication."""

    categories = [vote.unsafe_category for vote in unsafe_votes if vote.unsafe_category != "none"]
    return not categories or "other" in categories or len(set(categories)) > 1
