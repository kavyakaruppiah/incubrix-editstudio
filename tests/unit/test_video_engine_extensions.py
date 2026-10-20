"""
Unit tests for extended video editing engine capabilities:
- Split clip & Duplicate clip
- Wipe transition & 4:5 aspect ratio
- Vignette color grade effect
- Part 2 natural language prompt interpretation
- Scene detector & Thumbnail generator
- Gemini instruction adapter
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.engine.instruction_parser import InstructionParser
from app.engine.scene_detector import detect_scenes
from app.engine.thumbnail_generator import generate_thumbnail
from app.engine.timeline_engine import TimelineEngine
from app.models.media import MediaMetadata
from app.models.operation import OperationType
from app.models.timeline import Timeline, TimelineSegment
from app.models.transcript import Transcript
from app.providers.gemini_instruction import GeminiInstructionAdapter


@pytest.fixture
def base_timeline():
    metadata = MediaMetadata(
        duration=30.0,
        width=1920,
        height=1080,
        frame_rate=30.0,
        video_codec="h264",
        audio_present=True,
        sample_rate=44100,
        channels=2,
        is_vfr=False,
        file_size=10240,
    )
    initial_seg = TimelineSegment(
        segment_id="seg_01",
        source_start=0.0,
        source_end=30.0,
        speed=1.0,
    )
    return Timeline(
        schema_version="1.0.0",
        media_id="med_test123",
        original_media_hash="a" * 64,
        source_metadata=metadata,
        segments=[initial_seg],
    )


def test_split_clip(base_timeline):
    engine = TimelineEngine(base_timeline)
    assert len(engine.timeline.segments) == 1

    # Split in half at 15.0s
    op = engine.apply_split_clip(split_time=15.0)
    assert op.operation_type == OperationType.SPLIT_CLIP
    assert len(engine.timeline.segments) == 2

    seg1 = engine.timeline.segments[0]
    seg2 = engine.timeline.segments[1]

    assert seg1.source_start == 0.0
    assert seg1.source_end == 15.0

    assert seg2.source_start == 15.0
    assert seg2.source_end == 30.0


def test_split_clip_boundary_errors(base_timeline):
    engine = TimelineEngine(base_timeline)
    with pytest.raises(Exception):
        engine.apply_split_clip(split_time=0.0)

    with pytest.raises(Exception):
        engine.apply_split_clip(split_time=30.0)

    with pytest.raises(Exception):
        engine.apply_split_clip(split_time=45.0)


def test_duplicate_clip(base_timeline):
    engine = TimelineEngine(base_timeline)
    assert len(engine.timeline.segments) == 1

    op = engine.apply_duplicate_clip(segment_index=0)
    assert op.operation_type == OperationType.DUPLICATE_CLIP
    assert len(engine.timeline.segments) == 2

    assert engine.timeline.segments[0].segment_id != engine.timeline.segments[1].segment_id
    assert engine.timeline.segments[1].source_start == 0.0
    assert engine.timeline.segments[1].source_end == 30.0
    assert engine.timeline.total_output_duration == 60.0


def test_aspect_ratio_4_5(base_timeline):
    engine = TimelineEngine(base_timeline)
    op = engine.apply_aspect_ratio("4:5")
    assert op.operation_type == OperationType.SET_ASPECT_RATIO
    assert engine.timeline.aspect_ratio == "4:5"


def test_wipe_transition(base_timeline):
    engine = TimelineEngine(base_timeline)
    engine.apply_split_clip(15.0)
    op = engine.apply_transition("wipe", duration=1.0)
    assert op.operation_type == OperationType.ADD_TRANSITION
    assert engine.timeline.segments[1].transition_in == "wipe"
    assert engine.timeline.segments[1].transition_duration == 1.0


def test_vignette_color_grade(base_timeline):
    engine = TimelineEngine(base_timeline)
    op = engine.apply_color_grade(vignette=True)
    assert op.operation_type == OperationType.COLOR_GRADE
    assert engine.timeline.video_effects.vignette is True


def test_reset_color_grade_restores_all_color_defaults(base_timeline):
    engine = TimelineEngine(base_timeline)
    engine.apply_color_grade(preset="warm", brightness=0.2, saturation=1.4, vignette=True)
    engine.apply_color_grade(preset="original")
    effects = engine.timeline.video_effects
    assert effects.color_grade is None
    assert effects.brightness == 0.0
    assert effects.contrast == 1.0
    assert effects.saturation == 1.0
    assert effects.gamma == 1.0
    assert effects.vignette is False


def test_part2_prompts_interpretation(base_timeline):
    """Verify all Part 2 example prompts are recognized and produce structured proposals."""
    parser = InstructionParser()
    prompts = [
        ("Make my video cinematic.", OperationType.COLOR_GRADE),
        ("Make this video brighter and more colorful.", OperationType.COLOR_GRADE),
        ("Apply a vintage film look.", OperationType.COLOR_GRADE),
        ("Add a vignette.", OperationType.COLOR_GRADE),
        ("Add smooth transitions.", OperationType.ADD_TRANSITION),
        ("Add a wipe transition.", OperationType.ADD_TRANSITION),
        ("Convert this landscape video to a vertical short.", OperationType.SET_ASPECT_RATIO),
        ("Change aspect ratio to 4:5 portrait.", OperationType.SET_ASPECT_RATIO),
        ("Make dialogue clearer.", OperationType.AUDIO_DENOISE),
        ("Reduce background noise.", OperationType.AUDIO_DENOISE),
        ("Split the clip at 10 seconds.", OperationType.SPLIT_CLIP),
        ("Duplicate the first clip.", OperationType.DUPLICATE_CLIP),
        ("Add a watermark saying Confidential.", OperationType.ADD_TEXT_OVERLAY),
        ("Add credits at the end.", OperationType.ADD_TEXT_OVERLAY),
    ]

    for user_prompt, expected_op in prompts:
        proposal = parser.parse_instruction(user_prompt, base_timeline)
        assert proposal is not None, f"Prompt failed to parse: {user_prompt}"
        assert proposal.operation_type == expected_op, f"Expected {expected_op} but got {proposal.operation_type} for prompt '{user_prompt}'"

    first_clip = parser.parse_instruction("Duplicate the first clip.", base_timeline)
    assert first_clip.parameters["index"] == 0
    reset_grade = parser.parse_instruction("reset colour grade", base_timeline)
    assert reset_grade.operation_type == OperationType.COLOR_GRADE
    assert reset_grade.parameters["preset"] == "original"
    watermark = parser.parse_instruction("add watermark", base_timeline)
    assert watermark.parameters["text"] == "IncuBrix EditStudio"
    credits = parser.parse_instruction("add credits at the end", base_timeline)
    assert credits.parameters["text"] == "Edited with IncuBrix EditStudio"


def test_gemini_adapter_parsing():
    adapter = GeminiInstructionAdapter(api_key="test_dummy_key")

    mock_resp_json = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "actions": [
                                    {
                                        "operation": "color_grade",
                                        "parameters": {"preset": "cinematic", "contrast": 1.2},
                                        "description": "Cinematic visual tone",
                                    },
                                    {
                                        "operation": "set_aspect_ratio",
                                        "parameters": {"aspect_ratio": "9:16"},
                                        "description": "Vertical reel format",
                                    },
                                ],
                                "unsupported": [],
                                "clarification": "",
                            })
                        }
                    ]
                }
            }
        ]
    }

    with patch("app.providers.gemini_instruction.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_resp_json).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        plan = adapter.plan_prompt("Make it cinematic for TikTok reels", {"duration": 30.0})
        assert set(plan) == {"actions", "unsupported", "clarification"}
        assert len(plan["actions"]) == 2
        assert plan["actions"][0]["operation"] == "color_grade"
        assert plan["actions"][1]["operation"] == "set_aspect_ratio"

