import pytest
from pathlib import Path
from app.engine.time_policy import resolve_anchor_words_to_output_range
from app.engine.timeline_engine import TimelineEngine
from app.models.media import MediaMetadata
from app.models.timeline import Timeline, TimelineSegment
from app.transcription.fixture_adapter import FixtureTranscriptionAdapter

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def timeline_with_transcript():
    adapter = FixtureTranscriptionAdapter(FIXTURES_DIR / "sample_transcript.json")
    transcript = adapter.transcribe("dummy.mp4")

    metadata = MediaMetadata(
        duration=12.0,
        width=320,
        height=240,
        frame_rate=30.0,
        video_codec="h264",
        audio_present=True,
        sample_rate=48000,
        channels=1,
        is_vfr=False,
        file_size=500000,
    )
    initial_seg = TimelineSegment(segment_id="seg_1", source_start=0.0, source_end=12.0)
    return Timeline(
        schema_version="1.0.0",
        media_id="med_cap_test",
        original_media_hash="b" * 64,
        source_metadata=metadata,
        transcript=transcript,
        segments=[initial_seg],
    )


def test_11_caption_anchoring(timeline_with_transcript):
    """Scenario 11: Caption correctly anchors to transcript word IDs."""
    engine = TimelineEngine(timeline_with_transcript)
    # w_0021 is "goodbye" at 10.7s to 11.2s
    engine.apply_add_caption("Farewell!", ["w_0021"], anchor_phrase="goodbye")
    assert len(engine.timeline.captions) == 1
    assert engine.timeline.captions[0].anchor_word_ids == ["w_0021"]


def test_12_caption_stability_after_cuts(timeline_with_transcript):
    """Scenario 12: Caption output timing shifts accurately after preceding cuts."""
    engine = TimelineEngine(timeline_with_transcript)
    engine.apply_add_caption("Goodbye Note", ["w_0021"])

    # Cut 2s to 5s (3 seconds removed before word at 10.7s)
    engine.apply_cut(2.0, 5.0)

    word = engine.timeline.transcript.get_word_by_id("w_0021")
    out_start, out_end, status = resolve_anchor_words_to_output_range(engine.timeline.segments, [word])

    assert status == "anchored"
    # Original start 10.7 - 3.0 = 7.7
    assert abs(out_start - 7.7) < 1e-3


def test_13_caption_stability_after_speed_changes(timeline_with_transcript):
    """Scenario 13: Caption output timing scales correctly after preceding speed changes."""
    engine = TimelineEngine(timeline_with_transcript)
    engine.apply_add_caption("Goodbye Note", ["w_0021"])

    # Speed up 0s to 6s by 2x (6s becomes 3s, shifting later content 3s earlier)
    engine.apply_speed_change(0.0, 6.0, 2.0)

    word = engine.timeline.transcript.get_word_by_id("w_0021")
    out_start, out_end, status = resolve_anchor_words_to_output_range(engine.timeline.segments, [word])
    assert status == "anchored"
    # Original 10.7 - 3.0 = 7.7
    assert abs(out_start - 7.7) < 1e-3


def test_14_caption_stability_after_reordering(timeline_with_transcript):
    """Scenario 14: Caption output timing updates when segments are reordered."""
    engine = TimelineEngine(timeline_with_transcript)
    engine.apply_cut(6.0, 8.0)  # seg_a: 0..6, seg_b: 8..12
    # w_0021 is in seg_b (at 10.7s)
    engine.apply_add_caption("Goodbye Note", ["w_0021"])

    # Reorder seg_b before seg_a
    seg_ids = [s.segment_id for s in engine.timeline.segments]
    engine.apply_reorder([seg_ids[1], seg_ids[0]])

    word = engine.timeline.transcript.get_word_by_id("w_0021")
    out_start, out_end, status = resolve_anchor_words_to_output_range(engine.timeline.segments, [word])
    assert status == "anchored"
    # In seg_b (8..12) moved to output start 0. Offset is 10.7 - 8.0 = 2.7s
    assert abs(out_start - 2.7) < 1e-3


def test_15_removed_anchor_handling(timeline_with_transcript):
    """Scenario 15: When anchor word is cut, resolve_anchor_words returns 'removed'."""
    engine = TimelineEngine(timeline_with_transcript)
    engine.apply_add_caption("Goodbye Note", ["w_0021"])

    # Cut 10.0 to 12.0, completely removing w_0021
    engine.apply_cut(10.0, 12.0)

    word = engine.timeline.transcript.get_word_by_id("w_0021")
    out_start, out_end, status = resolve_anchor_words_to_output_range(engine.timeline.segments, [word])
    assert status == "removed"
    assert out_start is None
