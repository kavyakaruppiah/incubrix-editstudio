import pytest
from pathlib import Path
from app.engine.instruction_parser import ClarificationNeeded, InstructionParser
from app.models.media import MediaMetadata
from app.models.timeline import Timeline, TimelineSegment
from app.transcription.fixture_adapter import FixtureTranscriptionAdapter

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def sample_timeline():
    adapter = FixtureTranscriptionAdapter(FIXTURES_DIR / "sample_transcript.json")
    transcript = adapter.transcribe("dummy.mp4")
    metadata = MediaMetadata(
        duration=12.0,
        width=320,
        height=240,
        frame_rate=30.0,
        video_codec="h264",
        audio_present=True,
        file_size=500000,
    )
    return Timeline(
        media_id="med_parser_test",
        original_media_hash="c" * 64,
        source_metadata=metadata,
        transcript=transcript,
        segments=[TimelineSegment(segment_id="s1", source_start=0.0, source_end=12.0)],
    )


@pytest.mark.parametrize(
    "prompt",
    [
        'Add title card "welcome"',
        'Create an opening title card saying "Welcome to my channel"',
        'Put a title card with text "Adventure"',
    ],
)
def test_title_card_natural_phrasing_maps_to_real_text_overlay(sample_timeline, prompt):
    proposal = InstructionParser().parse_instruction(prompt, sample_timeline)

    assert proposal.operation_type == "add_text_overlay"
    assert proposal.parameters["text"] in {"welcome", "Welcome to my channel", "Adventure"}
    assert proposal.parameters["source_start"] == 0.0
    assert proposal.parameters["source_end"] == 4.0


def test_direct_instruction_applies_natural_title_card(sample_timeline, monkeypatch):
    from app.engine.timeline_engine import TimelineEngine
    from app.services import instruction_service as instruction_service_module
    from app.services import media_service as media_service_module

    engine = TimelineEngine(sample_timeline)
    monkeypatch.setattr(instruction_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(instruction_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(media_service_module.media_service, "get_media_manifest", lambda media_id: None)

    result = instruction_service_module.instruction_service.process_instruction(
        sample_timeline.media_id,
        'Add title card "welcome"',
    )

    assert result.status.value == "applied"
    assert sample_timeline.text_overlays[-1].text == "welcome"


def test_18_ambiguous_repeated_phrases(sample_timeline):
    """Scenario 18: Repeated phrase without occurrence qualifier raises ClarificationNeeded."""
    parser = InstructionParser()
    # 'welcome to' appears twice in sample_transcript
    with pytest.raises(ClarificationNeeded) as excinfo:
        parser.parse_instruction("remove phrase 'welcome to'", sample_timeline)

    assert len(excinfo.value.options) == 2
    assert "opt_1" in [o.id for o in excinfo.value.options]
    assert "opt_2" in [o.id for o in excinfo.value.options]


def test_19_multi_speaker_targeting(sample_timeline):
    """Scenario 19: Specifying speaker disambiguates repeated phrase immediately."""
    parser = InstructionParser()
    proposal = parser.parse_instruction("remove phrase 'welcome to' spoken by Speaker B", sample_timeline)
    assert proposal.operation_type == "remove_phrase"
    assert proposal.parameters["start"] == 8.0  # Speaker B occurrence starts at 8.0s


def test_20_clarification_answer_resolution(sample_timeline):
    """Scenario 20: User choosing 'first' disambiguates repeated phrase immediately."""
    parser = InstructionParser()
    proposal = parser.parse_instruction("remove the first phrase 'welcome to'", sample_timeline)
    assert proposal.operation_type == "remove_phrase"
    assert proposal.parameters["start"] == 0.5  # First occurrence starts at 0.5s


def test_explicit_times_default_to_current_timeline_and_source_is_opt_in(sample_timeline):
    parser = InstructionParser()

    current = parser.parse_instruction("cut 2 to 5", sample_timeline)
    original = parser.parse_instruction("cut 2 to 5 in the original source", sample_timeline)

    assert current.parameters["time_basis"] == "current_timeline"
    assert original.parameters["time_basis"] == "source"


def test_applied_time_instruction_returns_time_policy_statement(sample_timeline, monkeypatch):
    from app.engine.timeline_engine import TimelineEngine
    from app.services import instruction_service as instruction_service_module
    from app.services import media_service as media_service_module

    engine = TimelineEngine(sample_timeline)
    monkeypatch.setattr(instruction_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(instruction_service_module.timeline_service, "save_timeline", lambda timeline: "hash")
    monkeypatch.setattr(media_service_module.media_service, "get_media_manifest", lambda media_id: None)

    result = instruction_service_module.instruction_service.process_instruction(
        sample_timeline.media_id, "cut 2 to 4"
    )

    assert result.status.value == "applied"
    assert result.time_policy == "Time policy: current timeline (before this edit)."
    assert result.time_policy in result.message


def test_rejected_out_of_range_time_instruction_still_reports_time_policy(sample_timeline, monkeypatch):
    from app.engine.timeline_engine import TimelineEngine
    from app.services import instruction_service as instruction_service_module
    from app.services import media_service as media_service_module

    engine = TimelineEngine(sample_timeline)
    monkeypatch.setattr(instruction_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(media_service_module.media_service, "get_media_manifest", lambda media_id: None)

    result = instruction_service_module.instruction_service.process_instruction(
        sample_timeline.media_id, "cut from 80 seconds to 90 seconds"
    )

    assert result.status.value == "rejected"
    assert result.time_policy == "Time policy: current timeline (before this edit)."
    assert result.time_policy in result.message


def test_whole_video_time_operations_clamp_to_current_duration(sample_timeline):
    proposal = InstructionParser().parse_instruction("mute video", sample_timeline)

    assert proposal.parameters["end"] == sample_timeline.total_output_duration
    assert proposal.parameters["time_basis"] == "current_timeline"


@pytest.mark.parametrize("prompt,expected_start,expected_end", [
    ("cut from 1h02m to 1h03m", 3720, 3780),
    ("remove from 80 seconds to one minute forty", 80, 100),
    ("keep the first 30 seconds", 0, 30),
    ("mute the last 10 seconds", 2, 12),
    ("bleep from 1 minute to 1 minute 20 seconds", 60, 80),
])
def test_spoken_time_ranges_resolve_to_current_timeline(sample_timeline, prompt, expected_start, expected_end):
    if expected_end > sample_timeline.source_metadata.duration:
        sample_timeline.source_metadata.duration = 4000.0
        sample_timeline.segments[0].source_end = 4000.0
    proposal = InstructionParser().parse_instruction(prompt, sample_timeline)

    assert proposal.parameters["time_basis"] == "current_timeline"
    assert proposal.parameters["start"] == expected_start
    assert proposal.parameters["end"] == expected_end


def test_spoken_time_range_can_explicitly_select_original_source(sample_timeline):
    sample_timeline.source_metadata.duration = 4000.0
    sample_timeline.segments[0].source_end = 4000.0
    proposal = InstructionParser().parse_instruction(
        "cut from 1h02m to 1h03m in the original source", sample_timeline
    )

    assert proposal.parameters["time_basis"] == "source"
    assert proposal.parameters["start"] == 3720
    assert proposal.parameters["end"] == 3780
