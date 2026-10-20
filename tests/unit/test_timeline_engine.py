import pytest
from pathlib import Path
from app.engine.canonical_hash import compute_timeline_hash
from app.engine.timeline_engine import TimelineEngine, TimelineValidationError
from app.models.media import MediaMetadata
from app.models.timeline import Timeline, TimelineSegment
from app.engine.time_policy import compute_segment_output_offsets
from app.transcription.fixture_adapter import FixtureTranscriptionAdapter

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def base_timeline():
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
    initial_seg = TimelineSegment(
        segment_id="seg_initial",
        source_start=0.0,
        source_end=12.0,
        speed=1.0,
    )
    return Timeline(
        schema_version="1.0.0",
        media_id="med_test_123",
        original_media_hash="a" * 64,
        source_metadata=metadata,
        transcript=transcript,
        segments=[initial_seg],
        revision=0,
    )


def test_clip_crossfade_overlaps_timeline_offsets_and_duration(base_timeline):
    base_timeline.segments = [
        TimelineSegment(segment_id="seg_a", source_start=0.0, source_end=6.0),
        TimelineSegment(
            segment_id="seg_b", source_start=6.0, source_end=12.0,
            transition_in="crossfade", transition_duration=0.75,
        ),
    ]
    engine = TimelineEngine(base_timeline)

    assert engine.timeline.total_output_duration == 11.25
    assert compute_segment_output_offsets(engine.timeline.segments) == [(0.0, 6.0), (5.25, 11.25)]

    engine.apply_transition("dissolve", 1.0)
    assert engine.timeline.segments[1].transition_in == "dissolve"
    assert engine.timeline.total_output_duration == 11.0

    engine.apply_transition("cut")
    assert engine.timeline.segments[1].transition_duration == 0
    assert engine.timeline.total_output_duration == 12.0


def test_current_timeline_cut_crossing_reordered_segments_resolves_disjoint_source_ranges(base_timeline):
    engine = TimelineEngine(base_timeline)
    engine.apply_cut(4.0, 8.0)
    first_id, second_id = [segment.segment_id for segment in engine.timeline.segments]
    engine.apply_reorder([second_id, first_id])

    operation = engine.apply_cut(3.0, 5.0, time_basis="current_timeline")

    assert [(segment.source_start, segment.source_end) for segment in engine.timeline.segments] == [
        (8.0, 11.0), (1.0, 4.0),
    ]
    assert operation.parameters["source_intervals"] == [[11.0, 12.0], [0.0, 1.0]]
    assert operation.parameters["source_intervals_ticks"] == [[990000, 1080000], [0, 90000]]
    assert operation.parameters["time_basis"] == "source"


def test_current_timeline_keep_crossing_reordered_segments_keeps_both_parts(base_timeline):
    engine = TimelineEngine(base_timeline)
    engine.apply_cut(4.0, 8.0)
    first_id, second_id = [segment.segment_id for segment in engine.timeline.segments]
    engine.apply_reorder([second_id, first_id])

    operation = engine.apply_keep_range(3.0, 5.0, time_basis="current_timeline")

    assert [(segment.source_start, segment.source_end) for segment in engine.timeline.segments] == [
        (11.0, 12.0), (0.0, 1.0),
    ]
    assert operation.parameters["source_intervals"] == [[11.0, 12.0], [0.0, 1.0]]
    assert engine.timeline.total_output_duration == 2.0


def test_current_timeline_speed_and_audio_effects_preserve_disjoint_source_anchors(base_timeline):
    engine = TimelineEngine(base_timeline)
    engine.apply_cut(4.0, 8.0)
    first_id, second_id = [segment.segment_id for segment in engine.timeline.segments]
    engine.apply_reorder([second_id, first_id])

    speed_op = engine.apply_speed_change(3.0, 5.0, 2.0, time_basis="current_timeline")
    assert speed_op.parameters["source_intervals"] == [[11.0, 12.0], [0.0, 1.0]]
    assert [(segment.source_start, segment.source_end, segment.speed) for segment in engine.timeline.segments] == [
        (8.0, 11.0, 1.0), (11.0, 12.0, 2.0),
        (0.0, 1.0, 2.0), (1.0, 4.0, 1.0),
    ]

    mute_op = engine.apply_mute(0.0, 1.0, time_basis="current_timeline")
    assert mute_op.parameters["source_intervals"] == [[8.0, 9.0]]
    assert engine.timeline.audio_effects.mutes[-1].source_start == 8.0
    assert engine.timeline.audio_effects.mutes[-1].source_end == 9.0


def test_06_cut_range_application(base_timeline):
    """Scenario 6: Applying a cut range correctly splits segments and updates output duration."""
    engine = TimelineEngine(base_timeline)
    op = engine.apply_cut(2.0, 5.0)

    assert op.operation_type == "cut_range"
    assert engine.timeline.revision == 1
    assert len(engine.timeline.segments) == 2
    # Seg 1: 0 to 2; Seg 2: 5 to 12
    assert engine.timeline.segments[0].source_end == 2.0
    assert engine.timeline.segments[1].source_start == 5.0
    assert engine.timeline.total_output_duration == 9.0


def test_07_keep_range_application(base_timeline):
    """Scenario 7: Keep-range retains only the specified interval."""
    engine = TimelineEngine(base_timeline)
    engine.apply_keep_range(3.0, 8.0)

    assert len(engine.timeline.segments) == 1
    assert engine.timeline.segments[0].source_start == 3.0
    assert engine.timeline.segments[0].source_end == 8.0
    assert engine.timeline.total_output_duration == 5.0


def test_08_reordering(base_timeline):
    """Scenario 8: Reordering existing segments."""
    engine = TimelineEngine(base_timeline)
    engine.apply_cut(4.0, 8.0)  # Produces 2 segments: [0..4] and [8..12]
    seg_ids = [s.segment_id for s in engine.timeline.segments]
    reordered_ids = [seg_ids[1], seg_ids[0]]

    engine.apply_reorder(reordered_ids)
    assert [s.segment_id for s in engine.timeline.segments] == reordered_ids
    assert engine.timeline.total_output_duration == 8.0


def test_generate_captions_requires_a_real_transcript(base_timeline):
    base_timeline.transcript.words = []
    engine = TimelineEngine(base_timeline)

    with pytest.raises(ValueError, match="no transcript.*Auto-Transcribe"):
        engine.apply_generate_captions()

    assert engine.timeline.revision == 0
    assert engine.timeline.captions == []
    assert engine.timeline.text_overlays == []


def test_09_speed_changes(base_timeline):
    """Scenario 9: Speed change correctly modifies segment speed and output duration."""
    engine = TimelineEngine(base_timeline)
    # Speed up 0s to 6s by 2x
    engine.apply_speed_change(0.0, 6.0, 2.0)
    # 6s / 2.0 = 3s output. Remaining 6s at 1x = 6s. Total = 9.0s
    assert abs(engine.timeline.total_output_duration - 9.0) < 1e-4


def test_10_mute_and_bleep(base_timeline):
    """Scenario 10: Adding mute and bleep effects."""
    engine = TimelineEngine(base_timeline)
    engine.apply_mute(1.0, 3.0)
    engine.apply_bleep(5.0, 6.0, frequency_hz=1000.0)

    assert len(engine.timeline.audio_effects.mutes) == 1
    assert len(engine.timeline.audio_effects.bleeps) == 1
    assert engine.timeline.audio_effects.bleeps[0].frequency_hz == 1000.0


def test_16_filler_word_removal(base_timeline):
    """Scenario 16: Detecting and removing filler words from timeline."""
    engine = TimelineEngine(base_timeline)
    op = engine.apply_remove_filler_words()
    assert op.operation_type == "remove_filler_words"
    assert len(engine.timeline.history) == 1
    assert op.parameters["removed_word_count"] >= 2
    assert engine.timeline.total_output_duration < 12.0


def test_17_silence_removal(base_timeline):
    """Scenario 17: Detecting and removing silence intervals > threshold."""
    engine = TimelineEngine(base_timeline)
    op = engine.apply_remove_silence(threshold_seconds=1.0)
    assert op.operation_type == "remove_silence"
    assert len(engine.timeline.history) == 1
    assert op.parameters["silence_count"] >= 1
    assert engine.timeline.total_output_duration < 12.0


def test_21_invalid_range_rejection(base_timeline):
    """Scenario 21: Rejection of invalid time ranges."""
    engine = TimelineEngine(base_timeline)
    with pytest.raises(ValueError):
        engine.apply_cut(5.0, 2.0)  # start > end

    with pytest.raises(ValueError):
        engine.apply_speed_change(2.0, 4.0, speed=-1.0)  # negative speed


def test_22_conflicting_operation_handling(base_timeline):
    """Scenario 22: Conflicting operations (e.g. cutting entire media to 0 segments)."""
    engine = TimelineEngine(base_timeline)
    with pytest.raises(TimelineValidationError):
        engine.apply_cut(0.0, 12.0)  # cuts entire video


def test_23_undo_operation(base_timeline):
    """Scenario 23: Undo reverts the timeline state to the previous revision."""
    engine = TimelineEngine(base_timeline)
    engine.apply_cut(2.0, 5.0)
    assert engine.timeline.revision == 1
    assert engine.timeline.total_output_duration == 9.0
    history_size = len(engine.timeline.history)

    engine.undo()
    assert engine.timeline.revision == 0
    assert engine.timeline.total_output_duration == 12.0
    assert len(engine.timeline.history) == history_size
    assert engine.timeline.history[0].state == "undone"


def test_24_redo_operation(base_timeline):
    """Scenario 24: Redo reapplies the last undone operation."""
    engine = TimelineEngine(base_timeline)
    engine.apply_cut(2.0, 5.0)
    engine.undo()
    assert engine.timeline.total_output_duration == 12.0

    engine.redo()
    assert engine.timeline.revision == 1
    assert engine.timeline.total_output_duration == 9.0
    assert engine.timeline.history[0].state == "active"


def test_new_edit_after_undo_disables_redo_without_erasing_history(base_timeline):
    engine = TimelineEngine(base_timeline)
    engine.apply_cut(1.0, 2.0)
    first_operation_id = engine.timeline.history[0].operation_id
    engine.undo()
    engine.apply_cut(3.0, 4.0)

    assert [operation.operation_id for operation in engine.timeline.history][0] == first_operation_id
    assert [operation.state for operation in engine.timeline.history] == ["disabled", "active"]
    with pytest.raises(ValueError, match="redo"):
        engine.redo()


def test_25_targeted_restoration(base_timeline):
    """Scenario 25: Targeted restoration to a specific earlier revision."""
    engine = TimelineEngine(base_timeline)
    engine.apply_cut(1.0, 3.0)  # Rev 1, dur 10.0
    engine.apply_cut(5.0, 7.0)  # Rev 2, dur 8.0
    assert engine.timeline.revision == 2

    # Restore to Rev 1
    engine.restore_edit_or_revision(target_revision=1)
    assert engine.timeline.revision == 3
    assert engine.timeline.total_output_duration == 10.0


def test_26_failed_operation_atomicity(base_timeline):
    """Scenario 26: Failed operation does not corrupt or modify committed timeline."""
    engine = TimelineEngine(base_timeline)
    initial_hash = compute_timeline_hash(engine.timeline.model_dump())
    initial_dur = engine.timeline.total_output_duration

    with pytest.raises(TimelineValidationError):
        engine.apply_cut(0.0, 12.0)  # invalid cut to 0 segments

    # State must be completely unmodified
    assert engine.timeline.revision == 0
    assert engine.timeline.total_output_duration == initial_dur
    assert compute_timeline_hash(engine.timeline.model_dump()) == initial_hash


def test_27_deterministic_timeline_hashes(base_timeline):
    """Scenario 27: Identical inputs and instruction sequence produce exact same hash."""
    engine1 = TimelineEngine(base_timeline.model_copy(deep=True))
    engine2 = TimelineEngine(base_timeline.model_copy(deep=True))

    engine1.apply_cut(2.0, 4.0)
    engine1.apply_speed_change(6.0, 10.0, 1.5)

    engine2.apply_cut(2.0, 4.0)
    engine2.apply_speed_change(6.0, 10.0, 1.5)

    hash1 = compute_timeline_hash(engine1.timeline.model_dump())
    hash2 = compute_timeline_hash(engine2.timeline.model_dump())
    assert hash1 == hash2
