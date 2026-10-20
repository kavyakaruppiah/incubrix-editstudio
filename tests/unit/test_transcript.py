import pytest
from pathlib import Path
from app.models.transcript import Transcript, TranscriptWord, normalize_text
from app.transcription.faster_whisper_adapter import FasterWhisperAdapter
from app.transcription.fixture_adapter import FixtureTranscriptionAdapter
import app.transcription.unified_transcriber as unified_transcriber_module
from app.transcription.unified_transcriber import UnifiedTranscriber
from app.config import settings

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_04_transcript_validation():
    """Scenario 4: Transcript validation against source bounds and interval invariants."""
    # Invalid interval start > end
    with pytest.raises(ValueError):
        TranscriptWord(id="w_1", text="bad", start=5.0, end=4.0)

    # Word exceeding duration
    t = Transcript(words=[TranscriptWord(id="w_1", text="late", start=15.0, end=16.0)])
    with pytest.raises(ValueError, match="exceeding media duration"):
        t.validate_against_source(source_duration=10.0)

    # Duplicate word ID
    t_dup = Transcript(words=[
        TranscriptWord(id="w_1", text="first", start=1.0, end=2.0),
        TranscriptWord(id="w_1", text="duplicate", start=2.0, end=3.0),
    ])
    with pytest.raises(ValueError, match="Duplicate word id"):
        t_dup.validate_against_source(source_duration=10.0)


def test_05_stable_word_ids():
    """Scenario 5: Persistent word IDs and normalized phrase matching."""
    adapter = FixtureTranscriptionAdapter(FIXTURES_DIR / "sample_transcript.json")
    transcript = adapter.transcribe("dummy_path.mp4")

    assert len(transcript.words) == 21
    assert transcript.words[0].id == "w_0001"
    assert transcript.words[0].text == "Hello"
    assert transcript.words[0].normalized_text == "hello"

    # Find phrase occurrences
    matches = transcript.find_phrase_occurrences("welcome to")
    assert len(matches) == 2
    assert matches[0][0].id == "w_0003"
    assert matches[1][0].id == "w_0016"


def test_40_missing_optional_transcription_model_behaviour():
    """Scenario 40: Graceful handling of missing optional transcription model."""
    adapter = FasterWhisperAdapter()
    available, msg = adapter.is_available()
    # Should report clear status without crashing
    assert isinstance(available, bool)
    assert isinstance(msg, str)
    assert len(msg) > 10
    if not available:
        with pytest.raises(RuntimeError):
            adapter.transcribe("dummy.mp4")


def test_cloud_transcription_fallback_is_disabled_by_default(tmp_path, monkeypatch):
    """Audio must remain local unless the Google fallback is explicitly enabled."""
    media_path = tmp_path / "source.mp4"
    media_path.write_bytes(b"fixture")
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fixture")
    transcriber = UnifiedTranscriber()
    google_calls = []

    monkeypatch.setattr(settings, "GOOGLE_SPEECH_FALLBACK_ENABLED", False)
    monkeypatch.setattr(
        unified_transcriber_module,
        "extract_voice_audio",
        lambda *args, **kwargs: audio_path,
    )
    monkeypatch.setattr(transcriber, "_get_wav_duration", lambda path: 4.0)
    monkeypatch.setattr(transcriber, "_transcribe_with_whisper", lambda *args, **kwargs: Transcript())
    monkeypatch.setattr(
        transcriber,
        "_transcribe_with_google_api",
        lambda *args, **kwargs: google_calls.append(True),
    )

    transcriber.transcribe(str(media_path))

    assert google_calls == []
