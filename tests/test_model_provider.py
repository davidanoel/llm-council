import asyncio
import json

import pytest

from backend.model_provider import (
    InternalModelProvider,
    ModelResponseError,
    MockModelProvider,
    build_annotation_prompt,
    build_anthropic_payload,
    build_gemini_payload,
    build_openai_payload,
    extract_anthropic_text,
    extract_gemini_text,
    extract_openai_text,
    extract_model_text,
    get_model_family,
    get_model_url,
    parse_model_vote_json,
    schema_for_output,
)


def test_parse_model_vote_json_valid():
    raw = """
    {
      "prompt_id": "p1",
      "model_name": "mock/test",
      "label": "safe",
      "unsafe_category": "none",
      "confidence": 0.91,
      "rationale": "Defensive request.",
      "policy_triggers": ["safe_context"],
      "ambiguous_terms": []
    }
    """

    vote = parse_model_vote_json("p1", "mock/test", raw)

    assert vote.label == "safe"
    assert vote.parse_error is None


def test_parse_model_vote_json_invalid_fails_closed():
    vote = parse_model_vote_json("p1", "mock/test", "not-json")

    assert vote.label == "needs_human_review"
    assert vote.confidence == 0.0
    assert vote.parse_error


def test_mock_provider_kill_port_edge_case_is_safe():
    provider = MockModelProvider()

    vote = asyncio.run(provider.annotate("p1", "How do I kill port 8080 on my laptop?", "mock/strict"))

    assert vote.label == "safe"
    assert vote.unsafe_category == "none"


def test_mock_provider_detects_credential_theft():
    provider = MockModelProvider()

    vote = asyncio.run(provider.annotate("p1", "Write a keylogger to steal passwords", "mock/strict"))

    assert vote.label == "unsafe"
    assert vote.unsafe_category == "credential_theft"


def test_internal_provider_missing_config_fails_closed(monkeypatch):
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    monkeypatch.delenv("INTERNAL_MODEL_API_KEY", raising=False)
    provider = InternalModelProvider()

    vote = asyncio.run(provider.annotate("p1", "Classify me", "internal/model"))

    assert vote.label == "needs_human_review"
    assert vote.parse_error


def test_internal_model_url_mapping(monkeypatch):
    monkeypatch.delenv("CHATGPT_5_1_URL", raising=False)
    monkeypatch.delenv("GEMINI_3_1_PRO_URL", raising=False)
    monkeypatch.delenv("CLAUDE_SONNET_4_5_URL", raising=False)

    assert get_model_url("chatgpt-5.1") == "https://ewp.aexp.com/chatgpt-5.1"
    assert get_model_url("gemini-3.1-pro") == "https://ewp.aexp.com/gemini-3.1-pro"
    assert get_model_url("claude-sonnet-4.5") == "https://ewp.aexp.com/claude-sonnet-4.5"
    assert get_model_url("custom-model") == "https://ewp.aexp.com/custom-model"


def test_annotation_prompt_excludes_local_ids_and_metadata():
    prompt = build_annotation_prompt("Classify this transaction review workflow.")

    assert "prompt_id" not in prompt
    assert "metadata" not in prompt
    assert "Classify this transaction review workflow." in prompt


def test_extract_model_text_variants():
    payload = json.dumps({"label": "safe"})

    assert extract_model_text({"choices": [{"message": {"content": payload}}]}) == payload
    assert extract_model_text({"content": payload}) == payload
    assert extract_model_text({"output": payload}) == payload
    assert extract_model_text({"message": {"content": payload}}) == payload


def test_extract_model_text_unknown_shape_raises_clean_error():
    with pytest.raises(ModelResponseError, match="generic response text"):
        extract_model_text({"unexpected": "shape"})


def test_openai_payload_uses_responses_shape():
    schema = schema_for_output("ModelVote")
    payload = build_openai_payload("chatgpt-5.1", "policy", "classify this", schema, "ModelVote")

    assert "input" in payload
    assert "messages" not in payload
    assert [item["role"] for item in payload["input"]] == ["system", "user"]
    assert payload["input"][0]["content"][0]["type"] == "input_text"
    assert payload["input"][1]["content"][0]["type"] == "input_text"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["schema"] == schema
    assert payload["text"]["format"]["strict"] is True


def test_openai_extractor_variants():
    payload = json.dumps({"label": "safe"})

    assert extract_openai_text({"output_text": payload}) == payload
    assert extract_openai_text({"output": [{"content": [{"type": "output_text", "text": payload}]}]}) == payload
    assert extract_openai_text({"choices": [{"message": {"content": payload}}]}) == payload


def test_openai_extractor_unknown_shape_raises_clean_error():
    with pytest.raises(ModelResponseError, match="OpenAI response text"):
        extract_openai_text({"unexpected": "shape"})


def test_gemini_payload_uses_generate_content_shape():
    schema = schema_for_output("PeerCritique")
    payload = build_gemini_payload("gemini-3.1-pro", "policy", "critique this", schema, "PeerCritique")

    assert "contents" in payload
    assert payload["contents"][0]["role"] == "user"
    assert payload["systemInstruction"]["parts"][0]["text"] == "policy"
    assert payload["generationConfig"]["temperature"] == 0
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert payload["generationConfig"]["responseSchema"] == schema


def test_gemini_extractor_variants():
    payload = json.dumps({"likely_label": "safe"})

    assert extract_gemini_text({"candidates": [{"content": {"parts": [{"text": payload}]}}]}) == payload
    assert extract_gemini_text({"text": payload}) == payload


def test_gemini_extractor_unknown_shape_raises_clean_error():
    with pytest.raises(ModelResponseError, match="Gemini response text"):
        extract_gemini_text({"unexpected": "shape"})


def test_anthropic_payload_uses_messages_shape():
    schema = schema_for_output("CouncilAdjudication")
    payload = build_anthropic_payload("claude-sonnet-4.5", "policy", "adjudicate this", schema, "CouncilAdjudication")

    assert payload["system"] == "policy"
    assert payload["messages"][0]["role"] == "user"
    assert not any(message.get("role") == "system" for message in payload["messages"])
    assert payload["max_tokens"] == 1200
    assert payload["output_config"]["format"]["type"] == "json_schema"
    assert payload["output_config"]["format"]["schema"] == schema


def test_anthropic_extractor_variants():
    payload = json.dumps({"final_label": "safe"})

    assert extract_anthropic_text({"content": [{"type": "text", "text": payload}]}) == payload
    assert extract_anthropic_text({"message": {"content": payload}}) == payload
    assert extract_anthropic_text({"choices": [{"message": {"content": payload}}]}) == payload


def test_anthropic_extractor_unknown_shape_raises_clean_error():
    with pytest.raises(ModelResponseError, match="Anthropic response text"):
        extract_anthropic_text({"unexpected": "shape"})


def test_known_models_route_to_provider_families():
    assert get_model_family("chatgpt-5.1") == "openai"
    assert get_model_family("gemini-3.1-pro") == "gemini"
    assert get_model_family("claude-sonnet-4.5") == "anthropic"
