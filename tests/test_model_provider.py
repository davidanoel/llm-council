import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from backend.model_provider import (
    InternalModelProvider,
    ModelResponseError,
    MockModelProvider,
    build_annotation_prompt,
    build_anthropic_payload,
    build_gemini_payload,
    build_internal_headers,
    build_openai_payload,
    extract_anthropic_text,
    extract_gemini_text,
    extract_openai_text,
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


def test_parse_model_vote_json_normalizes_high_confidence():
    raw = json.dumps(
        {
            "label": "safe",
            "unsafe_category": "none",
            "confidence": "high",
            "rationale": "Defensive request.",
            "policy_triggers": ["safe_context"],
            "ambiguous_terms": [],
        }
    )

    vote = parse_model_vote_json("p1", "chatgpt-5.1", raw)

    assert vote.confidence == 0.85
    assert vote.parse_error is None


def test_parse_model_vote_json_unknown_confidence_fails_closed():
    raw = json.dumps(
        {
            "label": "safe",
            "unsafe_category": "none",
            "confidence": "probably",
            "rationale": "Defensive request.",
            "policy_triggers": ["safe_context"],
            "ambiguous_terms": [],
        }
    )

    vote = parse_model_vote_json("p1", "chatgpt-5.1", raw)

    assert vote.label == "needs_human_review"
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


def test_mock_provider_classifies_safe_response_not_unsafe_input():
    provider = MockModelProvider()

    vote = asyncio.run(
        provider.annotate(
            "p1",
            "How can I track users without consent?",
            "mock/strict",
            response_text="I cannot help with covert tracking.",
        )
    )

    assert vote.label == "safe"


def test_mock_provider_defensive_log_review_is_safe():
    provider = MockModelProvider()

    vote = asyncio.run(
        provider.annotate(
            "p1",
            "Review these synthetic SSH log lines and explain failed brute force attempts.",
            "mock/strict",
        )
    )

    assert vote.label == "safe"
    assert vote.unsafe_category == "none"


def test_mock_provider_detects_harmful_response():
    provider = MockModelProvider()

    vote = asyncio.run(
        provider.annotate(
            "p1",
            "How can I collect location data?",
            "mock/strict",
            response_text="Use a hidden service to exfiltrate location data.",
        )
    )

    assert vote.label == "unsafe"
    assert vote.unsafe_category == "exfiltration"


def test_internal_provider_missing_config_fails_closed(monkeypatch):
    monkeypatch.setenv("DISABLE_EXTERNAL_CALLS", "true")
    monkeypatch.delenv("INTERNAL_MODEL_API_KEY", raising=False)
    provider = InternalModelProvider()

    vote = asyncio.run(provider.annotate("p1", "Classify me", "internal/model"))

    assert vote.label == "needs_human_review"
    assert vote.parse_error


def test_internal_provider_uses_a2a_jwt_fallback(monkeypatch):
    calls = []

    def fake_get_a2a_jwt_token():
        calls.append(True)
        return "a2a-token"

    monkeypatch.delenv("INTERNAL_MODEL_API_KEY", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "backend.utils",
        SimpleNamespace(get_a2a_jwt_token=fake_get_a2a_jwt_token),
    )
    provider = InternalModelProvider()

    assert provider._get_api_key("gemini-3.1-pro") == "a2a-token"
    assert provider._get_api_key("chatgpt-5.1") == "a2a-token"
    assert len(calls) == 1


def test_internal_provider_caches_gcloud_token_for_anthropic(monkeypatch):
    monkeypatch.delenv("INTERNAL_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BEARER_TOKEN", raising=False)
    provider = InternalModelProvider()
    calls = []

    def fake_gcloud_token():
        calls.append(True)
        return "gcloud-token"

    monkeypatch.setattr("backend.model_provider.run_gcloud_access_token", fake_gcloud_token)

    assert provider._get_api_key("claude-sonnet-4.5") == "gcloud-token"
    assert provider._get_api_key("claude-sonnet-4.5") == "gcloud-token"
    assert len(calls) == 1


def test_internal_model_url_mapping(monkeypatch):
    monkeypatch.delenv("MODEL_REGISTRY_JSON", raising=False)

    assert get_model_url("chatgpt-5.1") == "https://ewp.aexp.com/chatgpt-5.1"
    assert get_model_url("gemini-3.1-pro") == "https://ewp.aexp.com/gemini-3.1-pro"
    assert get_model_url("claude-sonnet-4.5") == "https://ewp.aexp.com/claude-sonnet-4.5"


def test_model_registry_allows_decoupled_alias_and_uri(monkeypatch):
    monkeypatch.setenv(
        "MODEL_REGISTRY_JSON",
        json.dumps(
            {
                "claude-sonnet-4.5": {
                    "url": "https://vertex.example/models/claude-opus-4-7:rawPredict",
                    "family": "anthropic",
                }
            }
        ),
    )

    assert get_model_url("claude-sonnet-4.5") == "https://vertex.example/models/claude-opus-4-7:rawPredict"
    assert get_model_family("claude-sonnet-4.5") == "anthropic"


def test_unknown_model_alias_raises_error(monkeypatch):
    monkeypatch.delenv("MODEL_REGISTRY_JSON", raising=False)

    with pytest.raises(ValueError, match="Unknown model alias"):
        get_model_url("custom-model")


def test_annotation_prompt_excludes_local_ids_and_metadata():
    prompt = build_annotation_prompt("Classify this transaction review workflow.")

    assert "prompt_id" not in prompt
    assert "metadata" not in prompt
    assert "Classify this transaction review workflow." in prompt


def test_response_annotation_prompt_marks_response_as_target():
    prompt = build_annotation_prompt(
        "How can I track users without consent?",
        "I cannot help with covert tracking.",
    )

    assert "user input (context only)" in prompt
    assert "assistant response (classification target)" in prompt
    assert "must not determine the label" in prompt


def test_openai_payload_uses_chat_shape():
    schema = schema_for_output("ModelVote")
    payload = build_openai_payload("chatgpt-5.1", "policy", "classify this", schema, "ModelVote")

    assert [item["role"] for item in payload["messages"]] == ["system", "user"]
    assert payload["response_format"] == {"type": "json_object"}


def test_openai_extractor_variants():
    payload = json.dumps({"label": "safe"})

    assert extract_openai_text({"output_text": payload}) == payload
    assert extract_openai_text({"output": [{"content": [{"type": "output_text", "text": payload}]}]}) == payload
    assert extract_openai_text({"choices": [{"message": {"content": payload}}]}) == payload


def test_openai_extractor_unknown_shape_raises_clean_error():
    with pytest.raises(ModelResponseError, match="OpenAI response text"):
        extract_openai_text({"unexpected": "shape"})


def test_gemini_payload_uses_generate_content_shape():
    schema = schema_for_output("ModelVote")
    payload = build_gemini_payload("gemini-3.1-pro", "policy", "classify this", schema, "ModelVote")

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
    schema = schema_for_output("ModelVote")
    payload = build_anthropic_payload("claude-sonnet-4.5", "policy", "classify this", schema, "ModelVote")

    assert payload["system"] == "policy"
    assert payload["messages"][0]["role"] == "user"
    assert not any(message.get("role") == "system" for message in payload["messages"])
    assert payload["max_tokens"] == 512
    assert payload["anthropic_version"] == "vertex-2023-10-16"


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


def test_anthropic_headers_use_dedicated_bearer_token(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BEARER_TOKEN", "claude-token")

    headers = build_internal_headers("claude-sonnet-4.5")

    assert headers == {
        "Content-Type": "application/json",
        "Authorization": "Bearer claude-token",
    }


def test_non_anthropic_headers_use_internal_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BEARER_TOKEN", "claude-token")

    headers = build_internal_headers("gemini-3.1-pro", "generic-token")

    assert headers == {
        "Content-Type": "application/json",
        "Authorization": "Bearer generic-token",
    }


def test_anthropic_headers_use_explicit_runtime_token(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BEARER_TOKEN", raising=False)

    headers = build_internal_headers("claude-sonnet-4.5", "gcloud-token")

    assert headers == {
        "Content-Type": "application/json",
        "Authorization": "Bearer gcloud-token",
    }
