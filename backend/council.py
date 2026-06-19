"""Independent-model voting and deterministic annotation aggregation."""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any, Dict, List, Optional

from .model_provider import get_council_models, get_provider
from .schemas import CouncilDecision, ModelVote


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
    """Apply a simple two-of-three majority to valid model votes."""

    if len(votes) != 3:
        return human_review(prompt_id, "Expected three independent model votes.", votes)

    successful_votes = [vote for vote in votes if not vote.parse_error]
    safe_votes = [vote for vote in successful_votes if vote.label == "safe"]
    unsafe_votes = [vote for vote in successful_votes if vote.label == "unsafe"]

    if len(safe_votes) >= 2:
        return CouncilDecision(
            prompt_id=prompt_id,
            final_label="safe",
            unsafe_category="none",
            confidence=round(average_confidence(safe_votes), 2),
            rationale=f"{len(safe_votes)} of 3 AI annotators voted safe.",
            human_review_reason=None,
            decision_type="auto_safe",
        )

    if len(unsafe_votes) >= 2:
        category = majority_unsafe_category(unsafe_votes)
        return CouncilDecision(
            prompt_id=prompt_id,
            final_label="unsafe",
            unsafe_category=category,
            confidence=round(average_confidence(unsafe_votes), 2),
            rationale=f"{len(unsafe_votes)} of 3 AI annotators voted unsafe.",
            human_review_reason=None,
            decision_type="auto_unsafe",
        )

    return human_review(
        prompt_id,
        "The AI annotators did not produce a valid safe or unsafe majority.",
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


def majority_unsafe_category(votes: List[ModelVote]) -> str:
    """Return a majority unsafe category, or other when categories split."""

    categories = [vote.unsafe_category for vote in votes if vote.unsafe_category != "none"]
    if not categories:
        return "other"
    category, count = Counter(categories).most_common(1)[0]
    return category if count >= 2 or len(categories) == 1 else "other"


def average_confidence(votes: List[ModelVote]) -> float:
    """Return average self-reported confidence for votes."""

    return sum(vote.confidence for vote in votes) / len(votes) if votes else 0.0
