import pytest

from app.transcription.elevenlabs_adapter import ElevenLabsTranscriptionAdapter


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "language_code": "eng",
            "language_probability": 0.97,
            "words": [
                {"type": "word", "text": "Hello", "start": 0.1, "end": 0.4, "speaker_id": "speaker_0", "logprob": -0.1},
                {"type": "spacing", "text": " ", "start": 0.4, "end": 0.4},
                {"type": "audio_event", "text": "laughter", "start": 0.5, "end": 0.8},
                {"type": "word", "text": "world!", "start": 0.5, "end": 0.9},
            ],
        }


def test_elevenlabs_adapter_maps_word_timestamps_to_transcript(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"sample media")
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("app.transcription.elevenlabs_adapter.httpx.post", fake_post)
    adapter = ElevenLabsTranscriptionAdapter(api_key="secret", timeout=9)
    result = adapter.transcribe(str(source), language="auto")

    assert seen["url"] == "https://api.elevenlabs.io/v1/speech-to-text"
    assert seen["headers"] == {"xi-api-key": "secret"}
    assert seen["data"]["model_id"] == "scribe_v2"
    assert seen["data"]["timestamps_granularity"] == "word"
    assert seen["timeout"] == 9
    assert result.language == "en"
    assert [word.text for word in result.words] == ["Hello", "world!"]
    assert result.words[0].id == "el_000001"
    assert result.words[0].speaker == "speaker_0"
    assert result.words[0].provenance == "elevenlabs_scribe"


def test_elevenlabs_adapter_requires_api_key():
    adapter = ElevenLabsTranscriptionAdapter(api_key="")
    available, message = adapter.is_available()
    assert available is False
    assert "ELEVENLABS_API_KEY" in message


def test_elevenlabs_adapter_sanitizes_provider_http_errors(monkeypatch, tmp_path):
    import httpx

    source = tmp_path / "source.mp4"
    source.write_bytes(b"sample media")
    response = httpx.Response(401, request=httpx.Request("POST", "https://api.elevenlabs.io"))

    def fail_post(*args, **kwargs):
        raise httpx.HTTPStatusError("private body", request=response.request, response=response)

    monkeypatch.setattr("app.transcription.elevenlabs_adapter.httpx.post", fail_post)
    adapter = ElevenLabsTranscriptionAdapter(api_key="never-show-this")
    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        adapter.transcribe(str(source))
    assert "never-show-this" not in str(error.value)

