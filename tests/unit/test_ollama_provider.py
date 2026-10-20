import json
import io
from urllib.error import HTTPError

import pytest

import app.providers.ollama_instruction as ollama_module
from app.providers.ollama_instruction import OllamaInstructionAdapter, OllamaProviderError
from app.engine.capability_registry import capability_registry
from app.services.plan_service import AIPlanService
from app.models.transcript import TranscriptWord


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.payload if size < 0 else self.payload[:size]


def test_ollama_adapter_splits_typed_compound_plan_with_schema(monkeypatch):
    adapter = OllamaInstructionAdapter("http://127.0.0.1:11434", "test-model", 1)
    seen = {}

    def fake_urlopen(request, timeout):
        seen["request"] = request
        seen["timeout"] = timeout
        return FakeResponse({"response": json.dumps({"actions": [
            {"operation": "cut_range", "parameters": {"start": 1, "end": 2}, "description": "Cut from 1 to 2"},
            {"operation": "generate_captions", "parameters": {}, "description": "Add subtitles"},
        ], "unsupported": [], "clarification": ""})})

    monkeypatch.setattr(ollama_module, "urlopen", fake_urlopen)

    clauses = adapter.split_prompt("Cut from 1 to 2 and add subtitles")

    assert clauses == ["Cut from 1 to 2", "Add subtitles"]
    request_payload = json.loads(seen["request"].data.decode("utf-8"))
    assert request_payload["model"] == "test-model"
    assert request_payload["format"]["properties"]["actions"]["maxItems"] == 30
    variants = request_payload["format"]["properties"]["actions"]["items"]["oneOf"]
    operation_schemas = {
        variant["properties"]["operation"]["enum"][0]: variant["properties"]["parameters"]
        for variant in variants
    }
    assert "cut_range" in operation_schemas
    assert "generate_captions" in operation_schemas
    assert "apply_preset" not in operation_schemas
    assert operation_schemas["cut_range"]["properties"]["start"]["type"] == "number"
    assert operation_schemas["cut_range"]["additionalProperties"] is False
    assert "natural-language planning layer" in request_payload["prompt"]
    assert "Registered tools" in request_payload["prompt"]
    assert seen["timeout"] == 1


def test_ollama_cloud_uses_key_and_chat_endpoint(monkeypatch):
    adapter = OllamaInstructionAdapter(
        "https://ollama.com", "qwen3-coder:480b-cloud", 1, api_key="test-secret"
    )
    seen = {}

    def fake_urlopen(request, timeout):
        seen["request"] = request
        return FakeResponse({"message": {"content": json.dumps({
            "actions": [{
                "operation": "cut_range",
                "parameters": {"start": 1, "end": 2},
                "description": "Cut the first section",
            }],
            "unsupported": [],
            "clarification": "",
        })}})

    monkeypatch.setattr(ollama_module, "urlopen", fake_urlopen)
    plan = adapter.plan_prompt("Cut the first section", {})

    request = seen["request"]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://ollama.com/api/chat"
    assert request.get_header("Authorization") == "Bearer test-secret"
    assert payload["model"] == "qwen3-coder:480b-cloud"
    assert payload["messages"][0]["role"] == "user"
    assert plan["actions"][0]["operation"] == "cut_range"


def test_ollama_cloud_availability_requires_key():
    adapter = OllamaInstructionAdapter("https://ollama.com", "cloud-model", 1, api_key="")

    available, message = adapter.is_available()

    assert available is False
    assert "OLLAMA_API_KEY" in message


def test_ollama_cloud_availability_does_not_query_local_model_tags(monkeypatch):
    adapter = OllamaInstructionAdapter("https://ollama.com", "cloud-model", 1, api_key="test-secret")
    monkeypatch.setattr(
        ollama_module,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("Cloud availability must not call the local tags endpoint"),
    )

    available, message = adapter.is_available()

    assert available is True
    assert "Ollama Cloud" in message


def test_ollama_candidate_tool_filter_keeps_full_fallback_for_unknown_language():
    adapter = OllamaInstructionAdapter("http://127.0.0.1:11434", "test-model", 1)
    assert adapter._candidate_tool_names("Please turn this into something more compelling") is None
    candidate_names = adapter._candidate_tool_names("remove the part about pricing")
    assert candidate_names == {"cut_range", "remove_phrase"}


def test_ollama_adapter_rejects_malformed_model_output(monkeypatch):
    adapter = OllamaInstructionAdapter("http://127.0.0.1:11434", "test-model", 1)
    monkeypatch.setattr(ollama_module, "urlopen", lambda request, timeout: FakeResponse({"response": "not json"}))

    with pytest.raises(OllamaProviderError, match="valid structured plan"):
        adapter.split_prompt("Add captions")


def test_ollama_adapter_requires_explicit_installed_model():
    with pytest.raises(OllamaProviderError, match="OLLAMA_MODEL"):
        OllamaInstructionAdapter("http://127.0.0.1:11434", "", 1)


def test_ollama_availability_reports_missing_model(monkeypatch):
    adapter = OllamaInstructionAdapter("http://127.0.0.1:11434", "missing-model", 1)
    monkeypatch.setattr(ollama_module, "urlopen", lambda request, timeout: FakeResponse({"models": [{"name": "other-model"}]}))

    available, message = adapter.is_available()

    assert available is False
    assert "not installed" in message


def test_ollama_availability_accepts_implicit_latest_tag(monkeypatch):
    adapter = OllamaInstructionAdapter("http://127.0.0.1:11434", "test-model", 1)
    monkeypatch.setattr(ollama_module, "urlopen", lambda request, timeout: FakeResponse({"models": [{"name": "test-model:latest"}]}))

    available, message = adapter.is_available()

    assert available is True
    assert "test-model" in message


def test_long_transcript_context_finds_late_semantic_match_and_stays_bounded():
    words = [
        TranscriptWord(
            id=f"w{i}", text=("cost" if i == 5998 else f"word{i}"),
            start=i * 0.6, end=i * 0.6 + 0.3,
            speaker="Guest" if i == 5998 else "Host",
            confidence=0.91,
        )
        for i in range(6000)
    ]

    context, selection = AIPlanService._select_transcript_context(words, "remove the part about pricing")

    assert selection == "matched_windows"
    assert len(context) <= 1200
    match = next(word for word in context if word["text"] == "cost")
    assert match["speaker"] == "Guest"
    assert match["confidence"] == 0.91
    assert match["start"] > 3000


def test_transcript_context_omitted_for_non_content_edit():
    words = [TranscriptWord(id="w1", text="hello", start=0, end=0.4)]

    context, selection = AIPlanService._select_transcript_context(words, "mute from 10 to 20 seconds")

    assert context == []
    assert selection == "omitted_irrelevant"


def test_unmatched_semantic_query_samples_the_entire_long_transcript():
    words = [
        TranscriptWord(id=f"w{i}", text=f"word{i}", start=i * 0.2, end=i * 0.2 + 0.1)
        for i in range(6000)
    ]

    context, selection = AIPlanService._select_transcript_context(words, "remove the boring part")

    assert selection == "distributed_excerpts"
    assert len(context) <= 1200
    assert context[0]["start"] == 0
    assert context[-1]["start"] > 1000


def test_ollama_missing_model_404_has_actionable_diagnostic(monkeypatch):
    adapter = OllamaInstructionAdapter("http://127.0.0.1:11434", "qwen2.5:1.5b", 1)

    def missing_model(request, timeout):
        raise HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error":"model \'qwen2.5:1.5b\' not found"}'))

    monkeypatch.setattr(ollama_module, "urlopen", missing_model)
    with pytest.raises(OllamaProviderError, match="ollama pull qwen2.5:1.5b"):
        adapter._request_json("/api/generate", {"model": adapter.model})


@pytest.mark.parametrize("operation, parameters, message", [
    ("speed_change", {"start": 0, "end": 5, "speed": 0}, "between 0.05x and 10x"),
    ("speed_change", {"start": 0, "end": 5, "speed": True}, "must be number"),
    ("cut_range", {"start": 5, "end": 1}, "earlier than its end"),
    ("reorder_sections", {"new_segment_order": ["seg1", 2]}, "must be a string"),
])
def test_registry_rejects_invalid_typed_or_semantic_arguments(operation, parameters, message):
    assert message in capability_registry.validate(operation, parameters)


def test_registry_rejects_non_finite_arguments():
    assert capability_registry.validate("speed_change", {"start": 0, "end": 5, "speed": float("nan")})
