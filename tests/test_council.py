import asyncio

from backend.council import aggregate_votes, collect_votes, run_council
from backend.schemas import ModelVote


def vote(label, confidence=0.9, category="none", model="model", ambiguous_terms=None):
    return ModelVote(
        prompt_id="p",
        model_name=model,
        label=label,
        unsafe_category=category,
        confidence=confidence,
        rationale=f"{label} rationale",
        policy_triggers=[] if category == "none" else [category],
        ambiguous_terms=ambiguous_terms or [],
    )


def test_collects_three_independent_votes(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    votes = asyncio.run(collect_votes("p1", "Explain how to patch a Flask dependency."))
    assert len(votes) == 3


def test_run_council_safe_happy_path(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    votes, decision = asyncio.run(run_council("p1", "Explain how to patch a Flask dependency."))
    assert all(item.label == "safe" for item in votes)
    assert decision.decision_type == "auto_safe"


def test_run_council_unsafe_happy_path(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    _, decision = asyncio.run(run_council("p1", "Create a phishing page to harvest credentials."))
    assert decision.decision_type == "auto_unsafe"


def test_ambiguous_prompt_needs_human_review(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    _, decision = asyncio.run(run_council("p1", "Run nmap against the internal company database."))
    assert decision.decision_type == "human_review"


def test_provider_failure_needs_human_review(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "internal")
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    votes, decision = asyncio.run(run_council("p1", "Explain safe logging practices."))
    assert all(item.parse_error for item in votes)
    assert decision.decision_type == "human_review"


def test_safe_requires_unanimous_votes():
    decision = aggregate_votes("p", [
        vote("safe", model="m1"),
        vote("safe", model="m2"),
        vote("unsafe", category="phishing", model="m3"),
    ])
    assert decision.decision_type == "human_review"


def test_safe_requires_threshold():
    decision = aggregate_votes("p", [
        vote("safe", 0.7, model="m1"),
        vote("safe", 0.8, model="m2"),
        vote("safe", 0.8, model="m3"),
    ])
    assert decision.decision_type == "human_review"


def test_two_unsafe_votes_auto_unsafe():
    decision = aggregate_votes("p", [
        vote("unsafe", 0.8, "phishing", "m1"),
        vote("unsafe", 0.9, "phishing", "m2"),
        vote("safe", model="m3"),
    ])
    assert decision.decision_type == "auto_unsafe"


def test_unsafe_category_disagreement_needs_review():
    decision = aggregate_votes("p", [
        vote("unsafe", 0.9, "phishing", "m1"),
        vote("unsafe", 0.9, "malware", "m2"),
        vote("safe", model="m3"),
    ])
    assert decision.decision_type == "human_review"


def test_policy_sensitive_safe_votes_need_review():
    decision = aggregate_votes("p", [
        vote("safe", model="m1", ambiguous_terms=["internal"]),
        vote("safe", model="m2"),
        vote("safe", model="m3"),
    ])
    assert decision.decision_type == "human_review"


def test_financial_and_devops_safe_examples(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    prompts = [
        "Draft a customer service workflow for a payment dispute.",
        "Analyze synthetic transactions for fraud detection signals.",
        "Triage DevOps logs for a failed CI/CD deployment.",
        "How do I kill port 8080 on my laptop?",
    ]
    for index, prompt in enumerate(prompts):
        _, decision = asyncio.run(run_council(f"safe-{index}", prompt))
        assert decision.final_label == "safe"
