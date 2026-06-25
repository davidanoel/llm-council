"""Pydantic schemas for cybersecurity prompt annotation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


Label = Literal["safe", "unsafe", "needs_human_review"]
HumanLabel = Literal["safe", "unsafe"]
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
TaskType = Literal["prompt_classification", "response_classification", "mixed"]
ReviewReasonType = Literal["none", "provider_failure", "disagreement", "abstention", "ambiguous"]


class AnnotationRequest(BaseModel):
    """Request to annotate one prompt."""

    prompt_id: Optional[str] = None
    prompt_text: str = Field(..., min_length=1)
    response_text: Optional[str] = Field(default=None, min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


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
    run: Optional["RunSummary"] = None


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


class CouncilDecision(BaseModel):
    """Deterministic council decision before any human override."""

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
    run_id: str
    label: HumanLabel
    unsafe_category: UnsafeCategory = "none"
    rationale: Optional[str] = None
    reviewer: str = "local-user"


class HumanReview(BaseModel):
    """Stored human review record."""

    label: HumanLabel
    unsafe_category: UnsafeCategory = "none"
    rationale: Optional[str] = None
    reviewer: str
    reviewed_at: str


class ReviewSuggestion(BaseModel):
    """Human-review reason and optional suggested label."""

    reason_type: ReviewReasonType
    suggested_label: Optional[HumanLabel] = None
    suggested_unsafe_category: UnsafeCategory = "none"


class AnnotationResult(BaseModel):
    """Stored annotation case."""

    item_id: Optional[str] = None
    run_id: Optional[str] = None
    prompt_id: str
    prompt_text: str
    response_text: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    row_number: Optional[int] = None
    error_message: Optional[str] = None
    votes: List[ModelVote] = Field(default_factory=list)
    adjudication: Optional[CouncilDecision] = None
    review_reason_type: ReviewReasonType = "none"
    suggested_label: Optional[HumanLabel] = None
    suggested_unsafe_category: UnsafeCategory = "none"
    human_reviews: List[HumanReview] = Field(default_factory=list)
    created_at: str
    updated_at: str


class RunSummary(BaseModel):
    """Stored annotation run summary."""

    run_id: str
    name: str
    source_filename: Optional[str] = None
    task_type: TaskType = "prompt_classification"
    policy_version: str = "cyber-policy-v1"
    model_config_json: Dict[str, Any] = Field(default_factory=dict)
    decision_rule_version: str = "majority-v1"
    status: Literal["running", "completed", "failed"] = "completed"
    total_items: int = 0
    completed_items: int = 0
    auto_safe: int = 0
    auto_unsafe: int = 0
    human_review: int = 0
    provider_failed: int = 0
    disagreement: int = 0
    abstention: int = 0
    ambiguous: int = 0
    failed_items: int = 0
    resumable_items: int = 0
    created_at: str
    completed_at: Optional[str] = None


class RunUpdate(BaseModel):
    """Editable run fields."""

    name: str = Field(..., min_length=1)


class ExportedLabel(BaseModel):
    """Flattened label record for downstream use."""

    run_id: str
    run_name: str
    task_type: TaskType
    row_number: Optional[int] = None
    prompt_id: str
    label: Label
    label_source: Literal["council", "human"]
    decision_type: DecisionType
    review_reason_type: ReviewReasonType = "none"
    confidence: Optional[float] = None
    unsafe_category: UnsafeCategory = "none"
    human_review_rationale: Optional[str] = None
    prompt_text: Optional[str] = None
    response_text: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    votes: List[ModelVote] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ExportPreview(BaseModel):
    """Counts that describe export readiness for one run."""

    run_id: str
    run_name: str
    task_type: TaskType
    total_items: int
    exportable_items: int
    failed_items: int
    unresolved_items: int
    human_reviewed_items: int
    ai_labeled_items: int


class ExportManifest(BaseModel):
    """Small manifest that travels with exported labels."""

    run_id: str
    run_name: str
    source_filename: Optional[str] = None
    task_type: TaskType
    model_provider: Optional[str] = None
    model_names: List[str] = Field(default_factory=list)
    policy_version: str
    decision_rule_version: str
    total_items: int
    exported_items: int
    failed_items: int
    unresolved_items: int
    human_reviewed_items: int
    ai_labeled_items: int
    created_at: str
    completed_at: Optional[str] = None
    model_config_json: Dict[str, Any] = Field(default_factory=dict)


class AgreementMetrics(BaseModel):
    """Dataset-level agreement among successful AI annotator panels."""

    fleiss_kappa: Optional[float]
    observed_agreement: Optional[float]
    unanimous_rate: Optional[float]
    complete_items: int
    excluded_items: int
    coverage_rate: float


class ExportAnalysis(BaseModel):
    """Agreement and final-label counts reconstructed from an export CSV."""

    agreement: AgreementMetrics
    total_items: int
    safe_items: int
    unsafe_items: int
    unresolved_items: int
    human_review_items: int


def utc_now() -> str:
    """Return an ISO UTC timestamp."""

    return datetime.utcnow().isoformat()
