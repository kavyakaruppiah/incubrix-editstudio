"""Focused regression coverage for the assessment hard-case scenarios.

These tests exercise deterministic local timeline/parser behavior. They do not
claim a real-world speaker diarization run or a final encoded-video review.
"""

from pathlib import Path

import pytest

from app.core.time_parser import parse_time_expression
from app.engine.instruction_parser import ClarificationNeeded, InstructionParser
from app.engine.timeline_engine import TimelineEngine, TimelineValidationError
from app.models.media import MediaMetadata
from app.models.timeline import Timeline, TimelineSegment
from app.models.transcript import Transcript, TranscriptWord
from app.rendering.plan_builder import resolve_source_range_to_output


FIXTURES = Path(__file__).parents[1] / "fixtures"


def make_timeline(words=None, *, duration=12.0, is_vfr=False):
    transcript = Transcript(words=words or [])
    return Timeline(
        media_id="assessment-hard-case",
        original_media_hash="d" * 64,
        source_metadata=MediaMetadata(
            duration=duration,
            width=320,
            height=240,
            frame_rate=30,
            video_codec="h264",
            audio_present=True,
            sample_rate=48000,
            channels=2,
            is_vfr=is_vfr,
            file_size=1000,
        ),
        transcript=transcript,
        segments=[TimelineSegment(segment_id="seg_initial", source_start=0, source_end=duration)],
    )


def test_case_01_caption_returns_after_anchored_sentence_cut_is_restored():
    words = [
        TranscriptWord(id="w1", text="A clear", start=1, end=1.4),
        TranscriptWord(id="w2", text="sentence.", start=1.4, end=2),
    ]
    engine = TimelineEngine(make_timeline(words))
    engine.apply_add_caption("A clear sentence.", ["w1", "w2"])
    cut = engine.apply_cut(1, 2, provenance="assessment_case_01")

    # The anchored phrase is fully removed, so the caption is no longer visible.
    assert engine.timeline.captions[0].anchor_word_ids == ["w1", "w2"]
    assert not resolve_source_range_to_output(engine.timeline, 1, 2)

    engine.restore_edit_or_revision(target_revision=cut.previous_revision)
    assert engine.timeline.captions[0].anchor_word_ids == ["w1", "w2"]
    assert resolve_source_range_to_output(engine.timeline, 1, 2)


def test_case_02_reorder_music_bleep_and_filler_cut_resolve_only_retained_audio():
    words = [
        TranscriptWord(id="w1", text="Start", start=0.5, end=0.9, speaker="Host"),
        TranscriptWord(id="w2", text="um", start=2, end=2.3, speaker="Guest"),
        TranscriptWord(id="w3", text="continue", start=3, end=3.6, speaker="Guest"),
    ]
    engine = TimelineEngine(make_timeline(words, duration=6))
    engine.apply_cut(1, 1.5)
    first, second = [segment.segment_id for segment in engine.timeline.segments]
    engine.apply_reorder([second, first])
    engine.apply_background_music(track_id="assessment_bgm", volume=0.15)
    engine.apply_mute(3, 3.6, word_ids=["w3"])
    engine.apply_bleep(2, 2.3, word_ids=["w2"])
    engine.apply_remove_filler_words()

    # The bleep remains source-anchored, but the removed filler has no output
    # interval; retained parts of an effect still map through the reordered edit.
    bleep = engine.timeline.audio_effects.bleeps[0]
    assert bleep.word_ids == ["w2"]
    assert resolve_source_range_to_output(engine.timeline, bleep.source_start, bleep.source_end) == []
    mute = engine.timeline.audio_effects.mutes[0]
    assert mute.word_ids == ["w3"]
    assert resolve_source_range_to_output(engine.timeline, mute.source_start, mute.source_end)
    assert engine.timeline.background_music.track_id == "assessment_bgm"
    assert engine.timeline.total_output_duration < 6


def test_case_03_natural_time_forms_and_out_of_range_time_are_checked():
    duration_ticks = 120 * 90_000
    assert parse_time_expression("80 seconds", duration_ticks).start_tick == 80 * 90_000
    assert parse_time_expression("a minute twenty", duration_ticks).start_tick == 80 * 90_000
    assert parse_time_expression("the last 10 seconds", duration_ticks).start_tick == 110 * 90_000
    with pytest.raises(ValueError):
        parse_time_expression("at 5:00", duration_ticks)

    # Repeating a source-relative cut must be rejected as a no-op, not added
    # to history as if new media had been removed.
    engine = TimelineEngine(make_timeline(duration=120))
    engine.apply_cut(30, 40)
    revision_after_first_cut = engine.timeline.revision
    with pytest.raises(ValueError, match="already be removed"):
        engine.apply_cut(30, 40)
    assert engine.timeline.revision == revision_after_first_cut


def test_case_04_undo_restores_cut_without_dropping_existing_music():
    engine = TimelineEngine(make_timeline(duration=12))
    engine.apply_background_music(track_id="keep_this_music", volume=0.2)
    engine.apply_cut(2, 4)
    engine.apply_cut(6, 8)
    engine.undo()

    assert engine.timeline.background_music.track_id == "keep_this_music"
    assert engine.timeline.total_output_duration == 10
    # The engine's undo is last-active-operation based; second-to-last-cut
    # targeting is not claimed by this regression.


def test_case_05_four_repeated_thanks_requests_clarification():
    words = []
    for index, start in enumerate((1, 3, 5, 7), start=1):
        words.append(TranscriptWord(id=f"thanks{index}", text="thanks", start=start, end=start + 0.4))
    timeline = make_timeline(words, duration=10)

    with pytest.raises(ClarificationNeeded) as clarification:
        InstructionParser().parse_instruction("remove everything after I say thanks", timeline)

    assert len(clarification.value.options) == 4
    assert [option.target_data["start"] for option in clarification.value.options] == [
        1.4, 3.4, 5.4, 7.4,
    ]

    # The selected clarification payload is an executable cut range beginning
    # after the chosen word, preserving that word itself.
    selected = clarification.value.options[2].target_data["parameters"]
    chosen_engine = TimelineEngine(timeline.model_copy(deep=True))
    chosen_engine.apply_cut(selected["start"], selected["end"])
    assert chosen_engine.timeline.total_output_duration == pytest.approx(5.4)


def test_case_06_ten_x_is_allowed_and_whole_video_cut_is_rejected():
    engine = TimelineEngine(make_timeline(duration=12))
    engine.apply_speed_change(1, 3, 10)
    assert any(segment.speed == 10 for segment in engine.timeline.segments)

    before_revision = engine.timeline.revision
    with pytest.raises(TimelineValidationError, match="entire video"):
        engine.apply_cut(0, 12)
    assert engine.timeline.revision == before_revision


def test_case_07_overlapping_speech_and_vfr_metadata_are_detectable():
    words = [
        TranscriptWord(id="host", text="hello", start=1, end=2, speaker="Host"),
        TranscriptWord(id="guest", text="yes", start=1.7, end=2.2, speaker="Guest"),
    ]
    timeline = make_timeline(words, duration=12, is_vfr=True)

    warnings = timeline.transcript.validate_against_source(timeline.source_metadata.duration)
    assert any("overlap" in warning for warning in warnings)
    assert timeline.source_metadata.is_vfr is True
    assert {word.speaker for word in timeline.transcript.words} == {"Host", "Guest"}
