"""Pydantic schemas for cybersecurity prompt annotation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


Label = Literal["safe", "unsafe", "needs_human_review"]
UnsafeCategory = Literal[
    "malware",
    "credential_theft",
    "phishing",
    "exploit_execution",
    "privilege_escalation",
    "evasion",
    "persistence",
    "exfiltration",
    "unauthorized_access",
    "prompt_injection",
    "data_leakage",
    "other",
    "none",
]
DecisionType = Literal["auto_safe", "auto_unsafe", "human_review"]


class AnnotationRequest(BaseModel):
    """Request to annotate one prompt."""

    prompt_id: Optional[str] = None
    prompt_text: str = Field(..., min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BatchAnnotationRequest(BaseModel):
    """Request to annotate multiple prompts."""

    prompts: List[AnnotationRequest]


class BatchProgress(BaseModel):
    """Batch annotation progress counters."""

    total: int = 0
    completed: int = 0
    failed: int = 0
    auto_safe: int = 0
    auto_unsafe: int = 0
    human_review: int = 0
    provider_failed: int = 0


class BatchAnnotationResponse(BaseModel):
    """Batch annotation response with final progress counters."""

    results: List["AnnotationResult"]
    progress: BatchProgress


class ModelVote(BaseModel):
    """One independent model annotation."""

    prompt_id: str
    model_name: str
    label: Label
    unsafe_category: UnsafeCategory = "none"
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    policy_triggers: List[str] = Field(default_factory=list)
    ambiguous_terms: List[str] = Field(default_factory=list)
    parse_error: Optional[str] = None


class PeerCritique(BaseModel):
    """A peer critique over anonymized model votes."""

    reviewer_model: str
    disagreement_found: bool
    likely_label: Label
    strongest_policy_trigger: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str


class CouncilAdjudication(BaseModel):
    """Final council decision before any human override."""

    prompt_id: str
    final_label: Label
    unsafe_category: UnsafeCategory = "none"
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    human_review_reason: Optional[str] = None
    decision_type: DecisionType


class HumanReviewRequest(BaseModel):
    """Human override for a prompt annotation."""

    prompt_id: str
    label: Label
    unsafe_category: UnsafeCategory = "none"
    rationale: Optional[str] = None
    reviewer: str = "local-user"
    notes: Optional[str] = None


class HumanReview(BaseModel):
    """Stored human review record."""

    label: Label
    unsafe_category: UnsafeCategory = "none"
    rationale: Optional[str] = None
    reviewer: str
    notes: Optional[str] = None
    reviewed_at: str


class AnnotationResult(BaseModel):
    """Stored annotation case."""

    prompt_id: str
    prompt_text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    votes: List[ModelVote] = Field(default_factory=list)
    critiques: List[PeerCritique] = Field(default_factory=list)
    adjudication: Optional[CouncilAdjudication] = None
    human_reviews: List[HumanReview] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ExportedLabel(BaseModel):
    """Flattened label record for downstream use."""

    prompt_id: str
    label: Label
    label_source: Literal["council", "human"]
    confidence: Optional[float] = None
    unsafe_category: UnsafeCategory = "none"
    prompt_text: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvaluationItem(BaseModel):
    """One gold label item for evaluation."""

    prompt_id: str
    label: Label


class EvaluationRequest(BaseModel):
    """Evaluate stored predictions against human-majority labels."""

    labels: List[EvaluationItem]


class EvaluationMetrics(BaseModel):
    """Binary unsafe-vs-safe metrics with abstention reported separately."""

    confusion_matrix: Dict[str, int]
    accuracy: Optional[float]
    unsafe_precision: Optional[float]
    unsafe_recall: Optional[float]
    unsafe_f1: Optional[float]
    mcc: Optional[float]
    false_positive_rate: Optional[float]
    false_negative_rate: Optional[float]
    abstention_rate: float
    coverage_rate: float
    total: int
    covered: int
    abstained: int


def utc_now() -> str:
    """Return an ISO UTC timestamp."""

    return datetime.utcnow().isoformat()
