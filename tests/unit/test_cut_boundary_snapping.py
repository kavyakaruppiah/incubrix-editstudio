import subprocess

from app.engine.snapping import adjust_cut_boundary
from app.models.transcript import TranscriptWord


def test_cut_boundary_inside_word_moves_to_role_specific_word_edge(monkeypatch):
    monkeypatch.setattr(
        "app.engine.snapping.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=b"", stderr=b""),
    )
    words = [TranscriptWord(id="w1", text="hello", start=1.0, end=1.6)]

    cut_start = adjust_cut_boundary("source.mp4", 1.3, 10, protected_words=words, boundary_role="start")
    cut_end = adjust_cut_boundary("source.mp4", 1.3, 10, protected_words=words, boundary_role="end")

    assert cut_start.snapped is True
    assert cut_start.adjusted_time == 1.0
    assert cut_start.reason == "no_audio_word_boundary"
    assert cut_end.snapped is True
    assert cut_end.adjusted_time == 1.6
    assert cut_end.reason == "no_audio_word_boundary"


def test_cut_boundary_outside_word_does_not_move_into_protected_word(monkeypatch):
    monkeypatch.setattr(
        "app.engine.snapping.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=b"", stderr=b""),
    )
    words = [TranscriptWord(id="w1", text="hello", start=1.0, end=1.6)]

    result = adjust_cut_boundary("source.mp4", 0.95, 10, protected_words=words, boundary_role="start")

    assert result.adjusted_time <= 1.0
    assert not (1.0 < result.adjusted_time < 1.6)
