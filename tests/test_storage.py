from backend import storage
from backend.schemas import AnnotationResult, CouncilDecision, HumanReviewRequest, utc_now


def test_save_load_annotation_and_human_override(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    annotation = AnnotationResult(
        prompt_id="p1",
        prompt_text="Explain patching.",
        metadata={"source": "test"},
        adjudication=CouncilDecision(
            prompt_id="p1",
            final_label="safe",
            unsafe_category="none",
            confidence=0.9,
            rationale="Safe.",
            decision_type="auto_safe",
        ),
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    storage.save_annotation(annotation)
    loaded = storage.load_annotation("p1")

    assert loaded is not None
    assert loaded.prompt_text == "Explain patching."

    reviewed = storage.add_human_review(
        HumanReviewRequest(prompt_id="p1", label="unsafe", reviewer="analyst", rationale="Human override.")
    )

    assert reviewed.human_reviews[-1].label == "unsafe"
    exported = storage.export_labels()
    assert exported[0].label == "unsafe"
    assert exported[0].label_source == "human"


def test_review_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    annotation = AnnotationResult(
        prompt_id="p1",
        prompt_text="Run nmap internally.",
        adjudication=CouncilDecision(
            prompt_id="p1",
            final_label="needs_human_review",
            unsafe_category="none",
            confidence=0.6,
            rationale="Ambiguous.",
            human_review_reason="Ambiguous.",
            decision_type="human_review",
        ),
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    storage.save_annotation(annotation)

    assert [item.prompt_id for item in storage.review_queue()] == ["p1"]
