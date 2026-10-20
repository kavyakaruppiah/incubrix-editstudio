from types import SimpleNamespace

import pytest

import app.transcription.audio_extractor as extractor
from app.transcription.audio_extractor import AudioExtractionError, extract_voice_audio


def test_no_audio_stream_is_reported_as_no_audio(tmp_path, monkeypatch):
    source = tmp_path / "silent.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(
        extractor,
        "probe_media_file",
        lambda _path: SimpleNamespace(audio_present=True),
    )
    monkeypatch.setattr(extractor.settings, "RENDER_OUTPUT_DIR", str(tmp_path / "renders"))
    monkeypatch.setattr(type(extractor.settings), "resolve_ffmpeg", lambda _self: "ffmpeg")
    monkeypatch.setattr(
        extractor.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stderr="Output file #0 does not contain any stream.",
        ),
    )

    assert extract_voice_audio(source) is None


def test_audio_decode_failure_is_reported_instead_of_empty_transcript(tmp_path, monkeypatch):
    source = tmp_path / "broken-audio.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(
        extractor,
        "probe_media_file",
        lambda _path: SimpleNamespace(audio_present=True),
    )
    monkeypatch.setattr(extractor.settings, "RENDER_OUTPUT_DIR", str(tmp_path / "renders"))
    monkeypatch.setattr(type(extractor.settings), "resolve_ffmpeg", lambda _self: "ffmpeg")
    responses = iter([
        SimpleNamespace(returncode=1, stderr="Audio filter failed"),
        SimpleNamespace(returncode=1, stderr="Invalid audio stream"),
    ])
    monkeypatch.setattr(extractor.subprocess, "run", lambda *args, **kwargs: next(responses))

    with pytest.raises(AudioExtractionError, match="Invalid audio stream"):
        extract_voice_audio(source)
