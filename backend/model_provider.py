"""Model provider abstraction for local and future internal model APIs."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from .policy import AMBIGUITY_TERMS, CYBERSECURITY_POLICY
from .schemas import ModelVote


load_dotenv()

DEFAULT_COUNCIL_MODELS = ["chatgpt-5.1", "gemini-3.1-pro", "claude-sonnet-4.5"]
LABELS = ["safe", "unsafe", "needs_human_review"]
UNSAFE_CATEGORIES = [
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


class ModelResponseError(ValueError):
    """Raised when a model response cannot be read."""


def model_urls() -> Dict[str, str]:
    """Return configured internal URLs for known models."""

    return {
        "chatgpt-5.1": os.getenv("CHATGPT_5_1_URL", "https://ewp.aexp.com/chatgpt-5.1"),
        "gemini-3.1-pro": os.getenv("GEMINI_3_1_PRO_URL", "https://ewp.aexp.com/gemini-3.1-pro"),
        "claude-sonnet-4.5": os.getenv("CLAUDE_SONNET_4_5_URL", "https://ewp.aexp.com/claude-sonnet-4.5"),
    }


def get_model_family(model_name: str) -> str:
    """Return provider family for a model name."""

    normalized = model_name.strip().lower()
    if normalized.startswith("chatgpt") or normalized.startswith("gpt"):
        return "openai"
    if normalized.startswith("gemini"):
        return "gemini"
    if normalized.startswith("claude"):
        return "anthropic"
    return "generic"


def schema_for_output(output_kind: str) -> Dict[str, Any]:
    """Return a JSON schema for a structured model output."""

    schemas = {
        "ModelVote": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "label",
                "unsafe_category",
                "confidence",
                "rationale",
                "policy_triggers",
                "ambiguous_terms",
            ],
            "properties": {
                "label": {"type": "string", "enum": LABELS},
                "unsafe_category": {"type": "string", "enum": UNSAFE_CATEGORIES},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "rationale": {"type": "string"},
                "policy_triggers": {"type": "array", "items": {"type": "string"}},
                "ambiguous_terms": {"type": "array", "items": {"type": "string"}},
            },
        },
    }
    if output_kind not in schemas:
        raise ValueError(f"Unknown output schema kind: {output_kind}")
    return schemas[output_kind]


def get_model_provider_name() -> str:
    """Return configured provider name."""

    return os.getenv("MODEL_PROVIDER", "internal").strip().lower() or "internal"


def external_calls_disabled() -> bool:
    """Return whether external calls are disabled."""

    return os.getenv("DISABLE_EXTERNAL_CALLS", "false").strip().lower() == "true"


def get_council_models() -> List[str]:
    """Return configured council model names."""

    configured = os.getenv("COUNCIL_MODELS")
    if not configured:
        return DEFAULT_COUNCIL_MODELS
    models = [model.strip() for model in configured.split(",") if model.strip()]
    return models or DEFAULT_COUNCIL_MODELS


def get_model_url(model_name: str) -> str:
    """Return the internal URL for a model."""

    normalized = model_name.strip()
    urls = model_urls()
    if normalized in urls:
        return urls[normalized]
    return f"https://ewp.aexp.com/{normalized}"


def build_openai_payload(
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    output_schema: Dict[str, Any],
    schema_name: str,
) -> Dict[str, Any]:
    """Build an OpenAI Chat Completions API style payload."""

    del model_name, output_schema, schema_name
    return {
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "response_format": {"type": "json_object"},
    }


def build_gemini_payload(
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    output_schema: Dict[str, Any],
    schema_name: str,
) -> Dict[str, Any]:
    """Build a Gemini generateContent style payload."""

    del model_name, schema_name
    return {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}],
            }
        ],
        "systemInstruction": {
            "parts": [{"text": system_prompt}],
        },
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 1200,
            "responseMimeType": "application/json",
            "responseSchema": output_schema,
        },
    }


def build_anthropic_payload(
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    output_schema: Dict[str, Any],
    schema_name: str,
) -> Dict[str, Any]:
    """Build an Anthropic Messages API style payload."""

    del schema_name
    return {
        "model": model_name,
        "system": system_prompt,
        "max_tokens": 1200,
        "messages": [
            {
                "role": "user",
                "content": user_prompt,
            }
        ],
        "output_config": {
            "format": {
                "type": "json_schema",
                "schema": output_schema,
            }
        },
    }


def build_generic_payload(model_name: str, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    """Build a simple generic chat payload."""

    return {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }


def get_model_bearer_token(model_name: str, internal_api_key: Optional[str] = None) -> Optional[str]:
    """Return the bearer token configured for a model family."""

    if get_model_family(model_name) == "anthropic":
        return os.getenv("ANTHROPIC_BEARER_TOKEN", "").strip() or None
    return internal_api_key.strip() if internal_api_key and internal_api_key.strip() else None


def build_internal_headers(model_name: str, api_key: Optional[str] = None) -> Dict[str, str]:
    """Build request headers with model-family-specific bearer auth."""

    headers = {"Content-Type": "application/json"}
    bearer_token = get_model_bearer_token(model_name, api_key)
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers


async def post_json(
    url: str,
    payload: Dict[str, Any],
    model_name: str,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """POST JSON to an internal model endpoint."""

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            headers=build_internal_headers(model_name, api_key),
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def call_model(model_name: str, system_prompt: str, user_prompt: str, output_kind: str, api_key: Optional[str] = None) -> str:
    """Call an internal model using its provider-compatible adapter."""

    family = get_model_family(model_name)
    output_schema = schema_for_output(output_kind)
    schema_name = output_kind

    if family == "openai":
        payload = build_openai_payload(model_name, system_prompt, user_prompt, output_schema, schema_name)
        extractor = extract_openai_text
    elif family == "gemini":
        payload = build_gemini_payload(model_name, system_prompt, user_prompt, output_schema, schema_name)
        extractor = extract_gemini_text
    elif family == "anthropic":
        payload = build_anthropic_payload(model_name, system_prompt, user_prompt, output_schema, schema_name)
        extractor = extract_anthropic_text
    else:
        payload = build_generic_payload(model_name, system_prompt, user_prompt)
        extractor = extract_generic_text

    response_json = await post_json(get_model_url(model_name), payload, model_name, api_key)
    return extractor(response_json)


def extract_openai_text(data: Dict[str, Any]) -> str:
    """Extract text from an OpenAI-style response."""

    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"]

    for item in data.get("output", []):
        for part in item.get("content", []):
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                return part["text"]

    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        if isinstance(message.get("content"), str):
            return message["content"]

    raise ModelResponseError("Could not extract OpenAI response text")


def extract_gemini_text(data: Dict[str, Any]) -> str:
    """Extract text from a Gemini-style response."""

    if isinstance(data.get("text"), str) and data["text"].strip():
        return data["text"]
    if isinstance(data.get("output"), str) and data["output"].strip():
        return data["output"]
    if isinstance(data.get("content"), str) and data["content"].strip():
        return data["content"]

    candidates = data.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            if isinstance(part.get("text"), str) and part["text"].strip():
                return part["text"]

    raise ModelResponseError("Could not extract Gemini response text")


def extract_anthropic_text(data: Dict[str, Any]) -> str:
    """Extract text from an Anthropic-style response."""

    for part in data.get("content", []):
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            return part["text"]

    if isinstance(data.get("message"), dict):
        message = data["message"]
        if isinstance(message.get("content"), str):
            return message["content"]

    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        if isinstance(message.get("content"), str):
            return message["content"]

    raise ModelResponseError("Could not extract Anthropic response text")


def extract_generic_text(data: Dict[str, Any]) -> str:
    """Extract text from common generic proxy response shapes."""

    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"]
    if isinstance(data.get("content"), str) and data["content"].strip():
        return data["content"]
    if isinstance(data.get("output"), str) and data["output"].strip():
        return data["output"]
    if isinstance(data.get("message"), dict) and isinstance(data["message"].get("content"), str):
        return data["message"]["content"]

    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        if isinstance(message.get("content"), str):
            return message["content"]

    candidates = data.get("candidates") or []
    if candidates:
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        if parts and isinstance(parts[0].get("text"), str):
            return parts[0]["text"]

    raise ModelResponseError("Could not extract generic response text")


def parse_model_vote_json(prompt_id: str, model_name: str, raw_text: str) -> ModelVote:
    """Parse a strict JSON model vote, failing closed on malformed output."""

    try:
        data = json.loads(raw_text)
        data.setdefault("prompt_id", prompt_id)
        data.setdefault("model_name", model_name)
        return ModelVote(**data)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        return fail_closed_vote(
            prompt_id,
            model_name,
            f"Provider returned invalid annotation JSON: {exc}",
        )


def fail_closed_vote(prompt_id: str, model_name: str, reason: str) -> ModelVote:
    """Return a needs_human_review vote for provider/config failures."""

    return ModelVote(
        prompt_id=prompt_id,
        model_name=model_name,
        label="needs_human_review",
        unsafe_category="none",
        confidence=0.0,
        rationale=reason,
        policy_triggers=["provider_failure"],
        ambiguous_terms=[],
        parse_error=reason,
    )


class BaseModelProvider:
    """Provider interface."""

    async def annotate(self, prompt_id: str, prompt_text: str, model_name: str, metadata: Optional[Dict[str, Any]] = None) -> ModelVote:
        raise NotImplementedError


class MockModelProvider(BaseModelProvider):
    """Deterministic local mock provider for development and tests."""

    async def annotate(self, prompt_id: str, prompt_text: str, model_name: str, metadata: Optional[Dict[str, Any]] = None) -> ModelVote:
        raw_vote = self._build_vote(prompt_id, prompt_text, model_name)
        return parse_model_vote_json(prompt_id, model_name, json.dumps(raw_vote))

    def _build_vote(self, prompt_id: str, prompt_text: str, model_name: str) -> Dict[str, Any]:
        text = prompt_text.lower()
        unsafe_category, triggers = classify_unsafe_category(text)
        ambiguous_terms = find_ambiguous_terms(text)

        if unsafe_category != "none":
            confidence = 0.88
            if "strict" in model_name:
                confidence = 0.94
            if "contextual" in model_name and contains_defensive_context(text):
                return {
                    "prompt_id": prompt_id,
                    "model_name": model_name,
                    "label": "needs_human_review",
                    "unsafe_category": unsafe_category,
                    "confidence": 0.62,
                    "rationale": "Potentially unsafe cyber detail appears in a possibly defensive context.",
                    "policy_triggers": triggers + ["dual_use_operational_detail"],
                    "ambiguous_terms": ambiguous_terms,
                }
            return {
                "prompt_id": prompt_id,
                "model_name": model_name,
                "label": "unsafe",
                "unsafe_category": unsafe_category,
                "confidence": confidence,
                "rationale": f"Prompt requests meaningful assistance related to {unsafe_category}.",
                "policy_triggers": triggers,
                "ambiguous_terms": ambiguous_terms,
            }

        if ambiguous_terms or contains_dual_use_detail(text):
            return {
                "prompt_id": prompt_id,
                "model_name": model_name,
                "label": "needs_human_review",
                "unsafe_category": "none",
                "confidence": 0.58,
                "rationale": "Authorization, ownership, or intent is ambiguous.",
                "policy_triggers": ["ambiguous_authorization"],
                "ambiguous_terms": ambiguous_terms,
            }

        return {
            "prompt_id": prompt_id,
            "model_name": model_name,
            "label": "safe",
            "unsafe_category": "none",
            "confidence": 0.9 if "strict" not in model_name else 0.86,
            "rationale": "Prompt fits safe defensive, educational, sysadmin, or normal software development use.",
            "policy_triggers": ["safe_context"],
            "ambiguous_terms": [],
        }


class InternalModelProvider(BaseModelProvider):
    """Internal model API adapter."""

    def __init__(self) -> None:
        self.api_key = os.getenv("INTERNAL_MODEL_API_KEY")

    def _ready(self) -> bool:
        return not external_calls_disabled()

    async def annotate(self, prompt_id: str, prompt_text: str, model_name: str, metadata: Optional[Dict[str, Any]] = None) -> ModelVote:
        if not self._ready():
            return fail_closed_vote(prompt_id, model_name, "Internal provider calls are disabled.")

        del metadata
        try:
            user_prompt = build_annotation_prompt(prompt_text)
            raw_text = await call_model(model_name, CYBERSECURITY_POLICY, user_prompt, "ModelVote", self.api_key)
            return parse_model_vote_json(prompt_id, model_name, raw_text)
        except Exception as exc:
            return fail_closed_vote(prompt_id, model_name, f"Internal provider call failed: {exc}")



def get_provider() -> BaseModelProvider:
    """Create the configured model provider."""

    provider_name = get_model_provider_name()
    if provider_name == "internal":
        return InternalModelProvider()
    return MockModelProvider()


def classify_unsafe_category(text: str) -> tuple[str, List[str]]:
    """Heuristic unsafe-category detector for the mock provider."""

    checks = [
        ("evasion", ["bypass fraud detection", "bypass controls", "evade fraud detection", "evade detection"]),
        ("phishing", ["impersonate customers", "impersonate a customer", "social engineering"]),
        ("unauthorized_access", ["synthetic identity", "synthetic identities", "exploit payment systems"]),
        ("credential_theft", ["steal password", "dump passwords", "credential", "session cookie", "keylogger"]),
        ("phishing", ["phishing", "fake login", "spoofed login", "harvest credentials"]),
        ("malware", ["malware", "ransomware", "trojan", "worm", "botnet", "payload"]),
        ("exploit_execution", ["exploit", "reverse shell", "shellcode", "metasploit", "cve-"]),
        ("privilege_escalation", ["privilege escalation", "privesc", "become root", "sudo bypass"]),
        ("evasion", ["bypass antivirus", "disable edr", "obfuscate payload", "stealth"]),
        ("persistence", ["persistence", "startup folder", "scheduled task", "launch agent"]),
        ("exfiltration", ["exfiltrate", "exfiltration", "send files to", "steal data"]),
        ("unauthorized_access", ["unauthorized", "break into", "hack into", "without permission"]),
        ("prompt_injection", ["ignore previous instructions", "system prompt", "jailbreak", "prompt injection"]),
        ("data_leakage", ["leak data", "dump database", "exfiltrate customer records", "misuse customer data", "misuse private data"]),
    ]
    for category, terms in checks:
        if any(term in text for term in terms):
            return category, [category]
    return "none", []


def contains_defensive_context(text: str) -> bool:
    """Return whether text includes defensive framing."""

    defensive_patterns = [
        r"\bdetect\b",
        r"\bdefend\b",
        r"\bpatch\b",
        r"\bincident response\b",
        r"\blog\b",
        r"\blogs\b",
        r"\bsecure\b",
        r"\bmitigate\b",
        r"\bfraud detection\b",
        r"\bfraud investigation\b",
        r"\bfraud analytics\b",
        r"\bchargeback\b",
        r"\bpayment dispute\b",
        r"\btransaction review\b",
        r"\brisk scoring\b",
        r"\baml\b",
        r"\bkyc\b",
        r"\bcustomer service\b",
        r"\baccount servicing\b",
        r"\bdevops\b",
        r"\bsre\b",
        r"\bci/cd\b",
        r"\bmonitoring\b",
        r"\balert triage\b",
        r"\bdebugging\b",
        r"\bdata analysis\b",
        r"\bcompliance analysis\b",
        r"\bpolicy analysis\b",
    ]
    return any(re.search(pattern, text) for pattern in defensive_patterns)


def contains_dual_use_detail(text: str) -> bool:
    """Return whether text appears operationally dual use."""

    return bool(re.search(r"\b(nmap|sqlmap|burp|powershell|curl|ssh|scp|chmod|iptables)\b", text))


def find_ambiguous_terms(text: str) -> List[str]:
    """Return ambiguity terms present in text."""

    if contains_defensive_context(text) and not classify_unsafe_category(text)[0] != "none":
        return []
    return sorted(term for term in AMBIGUITY_TERMS if term in text)


def build_annotation_prompt(prompt_text: str) -> str:
    """Build the strict JSON annotation task."""

    return f"""
Classify this prompt under the cybersecurity policy.

Return strict JSON with keys:
label, unsafe_category, confidence, rationale, policy_triggers,
ambiguous_terms.

Allowed labels: safe, unsafe, needs_human_review.
Allowed unsafe_category values: malware, credential_theft, phishing,
exploit_execution, privilege_escalation, evasion, persistence, exfiltration,
unauthorized_access, prompt_injection, data_leakage, other, none.

prompt:
{prompt_text}
""".strip()
