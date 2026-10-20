"""Offline, deterministic natural-language regression scenarios for CI."""
import pytest

from app.engine.instruction_parser import InstructionParser
from app.models.media import MediaMetadata
from app.models.operation import OperationType
from app.models.timeline import Timeline, TimelineSegment
from app.models.transcript import Transcript, TranscriptWord


SCENARIOS = [
    ("cut from 1 to 3", OperationType.CUT_RANGE),
    ("delete between 2 and 4", OperationType.CUT_RANGE),
    ("trim 2-5", OperationType.CUT_RANGE),
    ("remove first 2 seconds", OperationType.CUT_RANGE),
    ("cut the last 3 seconds", OperationType.CUT_RANGE),
    ("keep only from 2 to 8", OperationType.KEEP_RANGE),
    ("keep between 3 and 9", OperationType.KEEP_RANGE),
    ("keep first 5 seconds", OperationType.KEEP_RANGE),
    ("speed up 2x", OperationType.SPEED_CHANGE),
    ("make it 1.5x faster", OperationType.SPEED_CHANGE),
    ("slow down to 0.5x", OperationType.SPEED_CHANGE),
    ("speed up from 2 to 6 by 1.5x", OperationType.SPEED_CHANGE),
    ("mute from 2 to 4", OperationType.MUTE),
    ("mute the video", OperationType.MUTE),
    ("bleep from 2 to 4", OperationType.BLEEP),
    ("bleep word 'pricing'", OperationType.BLEEP),
    ("add caption 'Welcome!' at 'welcome to the channel'", OperationType.ADD_CAPTION),
    ("caption 'Subscribe' for 'goodbye'", OperationType.ADD_CAPTION),
    ("generate captions", OperationType.GENERATE_CAPTIONS),
    ("auto caption this", OperationType.GENERATE_CAPTIONS),
    ("add subtitles", OperationType.GENERATE_CAPTIONS),
    ("remove filler words", OperationType.REMOVE_FILLER_WORDS),
    ("clean up fillers", OperationType.REMOVE_FILLER_WORDS),
    ("cut um and uh", OperationType.REMOVE_FILLER_WORDS),
    ("remove silence longer than 1.5 seconds", OperationType.REMOVE_SILENCE),
    ("cut long pauses", OperationType.REMOVE_SILENCE),
    ("add background music with ducking", OperationType.ADD_BACKGROUND_MUSIC),
    ("bgm volume 0.3", OperationType.ADD_BACKGROUND_MUSIC),
    ("undo last edit", OperationType.UNDO),
    ("redo change", OperationType.REDO),
    ("start over", OperationType.RESTORE_EDIT),
    ("make this a vertical reel", OperationType.CREATE_REEL),
    ("set aspect ratio to 9:16", OperationType.SET_ASPECT_RATIO),
    ("make it square", OperationType.SET_ASPECT_RATIO),
    ("rotate video 90 degrees clockwise", OperationType.VIDEO_TRANSFORM),
    ("mirror video horizontally", OperationType.VIDEO_TRANSFORM),
    ("apply a cinematic color grade", OperationType.COLOR_GRADE),
    ("make the video sepia", OperationType.COLOR_GRADE),
    ("add a 1 second crossfade", OperationType.ADD_TRANSITION),
    ("add a smooth fade-in and fade-out", OperationType.ADD_TRANSITION),
    ("lower the music when someone speaks", OperationType.AUDIO_DUCKING),
    ("enable audio ducking", OperationType.AUDIO_DUCKING),
    ("blur the background", OperationType.BLUR_REGION),
    ("make this look like an educational video", OperationType.APPLY_PRESET),
    ("normalize audio", OperationType.AUDIO_NORMALIZE),
    ("reduce background noise", OperationType.AUDIO_DENOISE),
    ("apply audio noise reduction", OperationType.AUDIO_DENOISE),
    ("mudhal 10 seconds cut pannu", OperationType.CUT_RANGE),
    ("video-va 9:16 la maathu", OperationType.SET_ASPECT_RATIO),
    ("audio-va normalize pannu", OperationType.AUDIO_NORMALIZE),
]


@pytest.fixture
def scenario_timeline():
    metadata = MediaMetadata(
        duration=20.0, width=1280, height=720, frame_rate=30,
        video_codec="h264", audio_present=True, file_size=1000,
    )
    transcript = Transcript(words=[
        TranscriptWord(id=f"w{i}", text=word, start=start, end=end, confidence=0.98)
        for i, (word, start, end) in enumerate([
            ("welcome", 1.0, 1.4), ("to", 1.4, 1.6), ("the", 1.6, 1.8),
            ("channel", 1.8, 2.4), ("pricing", 4.0, 4.4), ("goodbye", 18.0, 18.4),
            ("um", 7.0, 7.2), ("uh", 7.3, 7.5),
        ], start=1)
    ])
    return Timeline(
        media_id="scenario", original_media_hash="a" * 64,
        source_metadata=metadata, transcript=transcript,
        segments=[TimelineSegment(segment_id="seg_1", source_start=0, source_end=20)],
    )


@pytest.mark.parametrize("prompt,expected", SCENARIOS, ids=[f"scenario-{i+1:02d}" for i in range(len(SCENARIOS))])
def test_prompt_scenario_resolves_to_expected_typed_operation(prompt, expected, scenario_timeline):
    proposal = InstructionParser().parse_instruction(prompt, scenario_timeline)
    assert proposal is not None, f"Scenario was not understood: {prompt}"
    assert proposal.operation_type == expected, f"Wrong operation for scenario: {prompt}"
    assert isinstance(proposal.parameters, dict)
