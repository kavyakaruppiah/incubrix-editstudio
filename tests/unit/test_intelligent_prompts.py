import pytest
from types import SimpleNamespace
from app.engine.instruction_parser import ClarificationNeeded, InstructionParser
from app.models.media import MediaMetadata
from app.models.timeline import Timeline, TimelineSegment
from app.models.transcript import Transcript, TranscriptWord
from app.models.operation import OperationType
from app.engine.timeline_engine import TimelineEngine
from app.engine.capability_registry import capability_registry
from app.services.instruction_service import instruction_service
from app.services.media_service import media_service
from app.services.plan_service import plan_service
import app.services.plan_service as plan_service_module
from app.services.timeline_service import timeline_service

@pytest.fixture
def mock_timeline():
    meta = MediaMetadata(
        duration=60.0,
        width=1920,
        height=1080,
        video_codec="h264",
        audio_present=True,
        file_size=1000000,
    )
    seg = TimelineSegment(segment_id="seg_1", source_start=0.0, source_end=60.0, speed=1.0)
    words = [
        TranscriptWord(id="w1", text="Welcome", start=1.0, end=1.8),
        TranscriptWord(id="w2", text="everyone", start=1.9, end=2.5),
        # Long pause from 2.5 to 5.0
        TranscriptWord(id="w3", text="to", start=5.0, end=5.2),
        TranscriptWord(id="w4", text="our", start=5.3, end=5.5),
        TranscriptWord(id="w5", text="channel", start=5.6, end=6.0),
        # Thank you sentence
        TranscriptWord(id="w6", text="Thank", start=40.0, end=40.4),
        TranscriptWord(id="w7", text="you", start=40.5, end=40.8),
        TranscriptWord(id="w8", text="all", start=40.9, end=41.2),
        TranscriptWord(id="w9", text="Goodbye", start=58.0, end=59.5),
    ]
    return Timeline(
        media_id="test_media_prompt",
        original_media_hash="0" * 64,
        source_metadata=meta,
        transcript=Transcript(words=words),
        segments=[seg],
        revision=5,
    )

def test_remove_first_10_seconds(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Remove the first 10 seconds.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.CUT_TIME
    assert prop.parameters["start_time"] == 0.0
    assert prop.parameters["end_time"] == 10.0

def test_tamil_thanglish_cut_10_seconds(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("mudhal 10 seconds cut pannu", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.CUT_TIME
    assert prop.parameters["start_time"] == 0.0
    assert prop.parameters["end_time"] == 10.0

def test_remove_all_long_pauses(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Remove all long pauses.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.REMOVE_SILENCE
    assert prop.parameters["min_silence_s"] >= 1.0

def test_find_and_mute_sentence(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Find where I say thank you and mute that sentence.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.MUTE_TIME
    # Word "Thank" starts at 40.0, "you" ends at 40.8
    assert prop.parameters["start_time"] <= 40.0
    assert prop.parameters["end_time"] >= 40.8

def test_make_ending_1_5x_faster(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Make the ending 1.5x faster.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.SPEED_CHANGE
    assert prop.parameters["speed"] == 1.5
    # Total duration is 60.0, ending is ~15-20%
    assert prop.parameters["start_time"] >= 45.0
    assert prop.parameters["end_time"] == 60.0


def test_final_n_seconds_speed_request_uses_exact_duration(mock_timeline):
    prop = InstructionParser().parse_instruction("Speed up the final 3 seconds to 1.5x", mock_timeline)
    assert prop.operation_type == OperationType.SPEED_CHANGE
    assert prop.parameters["start"] == 57.0
    assert prop.parameters["end"] == 60.0
    assert prop.parameters["speed"] == 1.5
    assert prop.parameters["target"] == "ending"


def test_screenshot_compound_prompt_is_fully_parsed_in_sequence(mock_timeline):
    prompt = (
        "Keep only the first 8 seconds, speed up the final 3 seconds to 1.5x, "
        "add captions from the transcript, and apply a warm cinematic color grade."
    )
    actions = plan_service._parse_supported_compound(prompt, mock_timeline)
    assert actions is not None
    assert [action["operation"] for action in actions] == [
        "keep_range", "speed_change", "generate_captions", "color_grade"
    ]
    assert actions[0]["parameters"]["start"] == 0.0
    assert actions[0]["parameters"]["end"] == 8.0
    assert actions[1]["parameters"]["start"] == 5.0
    assert actions[1]["parameters"]["end"] == 8.0
    assert actions[1]["parameters"]["speed"] == 1.5
    assert actions[3]["parameters"]["preset"] == "warm"


def test_time_range_tool_schemas_mark_required_fields():
    assert capability_registry.parameter_json_schema("keep_range")["required"] == ["start", "end"]
    assert capability_registry.parameter_json_schema("speed_change")["required"] == ["start", "end", "speed"]


@pytest.mark.parametrize(
    "prompt",
    [
        "Change the speed of the ending to 1.5x",
        "Change speed of ending to 1.5",
        "Set the speed of the outro at 1.5x",
        "Adjust the speed of the last part to 1.5x",
    ],
)
def test_normalized_ending_speed_prompts_are_supported(mock_timeline, prompt):
    prop = InstructionParser().parse_instruction(prompt, mock_timeline)
    assert prop.operation_type == OperationType.SPEED_CHANGE
    assert prop.parameters["target"] == "ending"
    assert prop.parameters["speed"] == 1.5
    assert prop.parameters["start"] == 45.0
    assert prop.parameters["end"] == 60.0


def test_normalized_ending_speed_plan_is_valid_and_applies(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "rules")

    plan = plan_service.generate_plan(
        mock_timeline.media_id,
        "Change the speed of the ending to 1.5x",
    )
    operation = plan["operations"][0]
    assert operation["validation_status"] == "valid"
    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])

    assert result["status"] == "applied"
    assert any(segment.speed == 1.5 for segment in engine.timeline.segments)

def test_create_vertical_reel(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Create a 30-second vertical reel from the most relevant sections.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.CREATE_REEL
    assert prop.parameters["target_duration"] == 30.0
    assert prop.parameters["aspect_ratio"] == "9:16"


def test_create_vertical_reel_instruction_is_applied(mock_timeline, monkeypatch):
    """A parsed create_reel operation must reach the deterministic timeline engine."""
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(media_service, "get_media_manifest", lambda media_id: None)

    result = instruction_service.process_instruction(
        mock_timeline.media_id,
        "Create a 30-second vertical reel",
    )

    assert result.status.value == "applied"
    assert engine.timeline.video_effects.aspect_ratio == "9:16"
    assert engine.timeline.total_output_duration == 30.0


def test_edit_plan_rolls_back_when_a_supported_operation_fails_at_runtime(mock_timeline, monkeypatch):
    """A real execution failure must still roll back the reviewed plan atomically."""
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(media_service, "get_media_manifest", lambda media_id: None)

    result = plan_service.apply_plan(
        mock_timeline.media_id,
        [
            {
                "type": "create_reel",
                "description": "Create a 30-second vertical reel",
                "parameters": {"target_duration_s": 30.0},
                "validation_status": "valid",
            },
            {
                "type": "speed_change",
                "description": "Set playback speed to zero",
                "parameters": {"start": 0, "end": 10, "speed": 0},
                "validation_status": "valid",
                "execution_mode": "structured",
            },
        ],
    )

    assert result["status"] == "rejected"
    assert result["applied_count"] == 0
    assert result["errors"]
    assert engine.timeline.revision == 5
    assert engine.timeline.total_output_duration == 60.0

def test_clean_subtitles_prompt(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Add clean subtitles with a white bold font and a black outline.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.SET_CAPTION_STYLE
    assert prop.parameters["primary_color"] == "#FFFFFF"
    assert prop.parameters["outline_color"] == "#000000"
    assert prop.parameters["bold"] is True

def test_karaoke_highlight_prompt(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Highlight each spoken word in yellow as it is spoken.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.SET_CAPTION_MODE
    assert prop.parameters["mode"] == "karaoke"
    assert prop.parameters["highlight_color"] == "#FFFF00"

def test_cinematic_color_grade(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Give the video a cinematic colour grade.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.COLOR_GRADE
    assert prop.parameters["preset"] == "cinematic"


@pytest.mark.parametrize(
    "prompt",
    [
        "Apply cinematic color preset",
        "Apply cinematic colour preset",
        "Cinematic color edit",
        "Add a cinematic color grade",
        "Make this video cinematic look",
    ],
)
def test_cinematic_color_prompt_aliases_are_supported(mock_timeline, prompt):
    prop = InstructionParser().parse_instruction(prompt, mock_timeline)
    assert prop.operation_type == OperationType.COLOR_GRADE
    assert prop.parameters["preset"] == "cinematic"


def test_cinematic_color_plan_can_be_approved_and_applied(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "rules")

    plan = plan_service.generate_plan(mock_timeline.media_id, "Cinematic color edit")
    operation = plan["operations"][0]
    assert operation["type"] == "color_grade"
    assert operation["validation_status"] == "valid"

    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])
    assert result["status"] == "applied"
    assert engine.timeline.video_effects.color_grade == "cinematic"


def test_cinematic_color_plan_uses_deterministic_match_before_ollama(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "ollama")

    def unexpected_model_call(*args, **kwargs):
        pytest.fail("A clear supported prompt should use the deterministic parser")

    monkeypatch.setattr(plan_service_module.OllamaInstructionAdapter, "plan_prompt", unexpected_model_call)
    plan = plan_service.generate_plan(
        mock_timeline.media_id,
        "Give the video a cinematic colour grade.",
    )
    assert plan["instruction_provider"] == "rules_fast_path"
    assert plan["operations_count"] == 1
    operation = plan["operations"][0]
    assert operation["type"] == "color_grade"
    assert operation["parameters"] == {"preset": "cinematic"}
    assert operation["validation_status"] == "valid"

    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])
    assert result["status"] == "applied"
    assert engine.timeline.video_effects.color_grade == "cinematic"


@pytest.mark.parametrize(
    "prompt",
    [
        "Remove background noise",
        "Reduce wind noise from the audio",
        "Clean up audio",
        "Apply audio noise reduction",
    ],
)
def test_audio_noise_reduction_prompt_is_recognized(mock_timeline, prompt):
    prop = InstructionParser().parse_instruction(prompt, mock_timeline)
    assert prop.operation_type == OperationType.AUDIO_DENOISE
    assert prop.parameters["enabled"] is True


def test_audio_noise_reduction_plan_can_be_approved_and_applied(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "rules")

    plan = plan_service.generate_plan(mock_timeline.media_id, "Remove background noise")
    assert plan["operations"][0]["validation_status"] == "valid"
    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])

    assert result["status"] == "applied"
    assert engine.timeline.audio_effects.noise_reduction_db == 12.0


@pytest.mark.parametrize(
    "prompt, expected",
    [
        ("Rotate video 90 degrees clockwise", {"rotation_degrees": 90}),
        ("Turn the clip 90 degrees left", {"rotation_degrees": 270}),
        ("Mirror the video horizontally", {"horizontal_flip": True, "vertical_flip": False}),
        ("Flip video vertically", {"horizontal_flip": False, "vertical_flip": True}),
    ],
)
def test_rotation_and_mirror_prompts_are_recognized(mock_timeline, prompt, expected):
    prop = InstructionParser().parse_instruction(prompt, mock_timeline)
    assert prop.operation_type == OperationType.VIDEO_TRANSFORM
    for key, value in expected.items():
        assert prop.parameters[key] == value


def test_transform_plan_can_be_approved_and_applied(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "rules")

    plan = plan_service.generate_plan(mock_timeline.media_id, "Mirror the video horizontally")
    assert plan["operations"][0]["validation_status"] == "valid"
    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])

    assert result["status"] == "applied"
    assert engine.timeline.video_effects.horizontal_flip is True


def test_ollama_unseen_multilingual_compound_plan_executes_typed_tools(mock_timeline, monkeypatch):
    """Novel wording is planned into typed tools and never sent back through the regex parser."""
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "ollama")

    class FakeOllama:
        def plan_prompt(self, prompt, context):
            assert prompt == "Make it paal-vannam and speed up the final 12 seconds to 1.5x"
            assert context["duration_seconds"] == 60.0
            return {
                "actions": [
                    {"operation": "color_grade", "parameters": {"preset": "grayscale"}, "description": "Convert the image to monochrome"},
                    {"operation": "speed_change", "parameters": {"start": 48.0, "end": 60.0, "speed": 1.5}, "description": "Accelerate the final section"},
                ],
                "unsupported": [],
                "clarification": "",
            }

    monkeypatch.setattr(plan_service_module, "OllamaInstructionAdapter", FakeOllama)
    plan = plan_service.generate_plan(mock_timeline.media_id, "Make it paal-vannam and speed up the final 12 seconds to 1.5x")

    assert [op["type"] for op in plan["operations"]] == ["color_grade", "speed_change"]
    assert all(op["execution_mode"] == "structured" for op in plan["operations"])
    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])

    assert result["status"] == "applied"
    assert result["applied_count"] == 2
    assert engine.timeline.video_effects.color_grade == "grayscale"
    assert any(segment.speed == 1.5 for segment in engine.timeline.segments)


def test_direct_instruction_api_uses_ai_plan_instead_of_keyword_parser(mock_timeline, monkeypatch):
    from app.api import routes
    from app.schemas.api_schemas import InstructionRequest

    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "ollama")

    class FakeOllama:
        def plan_prompt(self, prompt, context):
            assert prompt == 'Please put a welcome card at the beginning, it should say "welcome".'
            assert context["duration_seconds"] == 60.0
            return {
                "actions": [{
                    "operation": "add_text_overlay",
                    "parameters": {"text": "welcome", "position": "center", "source_start": 0, "source_end": 4},
                    "description": "Add the requested welcome title card",
                }],
                "unsupported": [],
                "clarification": "",
            }

    monkeypatch.setattr(plan_service_module, "OllamaInstructionAdapter", FakeOllama)
    result = routes.submit_instruction(
        mock_timeline.media_id,
        InstructionRequest(instruction='Please put a welcome card at the beginning, it should say "welcome".'),
    )

    assert result.status.value == "applied"
    assert mock_timeline.text_overlays[-1].text == "welcome"
    assert result.operations[-1].operation_type.value == "add_text_overlay"


def test_ollama_plan_cache_avoids_repeating_identical_parse(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "ollama")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_MODEL", "cache-test-model")
    plan_service_module.parse_cache.clear()

    calls = []

    class FakeOllama:
        def plan_prompt(self, prompt, context):
            calls.append((prompt, context))
            return {"actions": [], "unsupported": [], "clarification": ""}

    monkeypatch.setattr(plan_service_module, "OllamaInstructionAdapter", FakeOllama)
    first = plan_service.generate_plan(mock_timeline.media_id, "Cache this exact planning request")
    second = plan_service.generate_plan(mock_timeline.media_id, "Cache this exact planning request")

    assert len(calls) == 1
    assert first["operations"] == second["operations"] == []
    plan_service_module.parse_cache.clear()


def test_ollama_tries_coder_fallback_for_incomplete_primary_plan(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "ollama")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_MODEL", "primary-model")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_FALLBACK_MODELS", "coder-model,deepseek-model")
    calls = []

    class FakeOllama:
        def __init__(self, model=None):
            self.model = model or "primary-model"

        def plan_prompt(self, prompt, context):
            calls.append(self.model)
            if self.model == "primary-model":
                return {"actions": [], "unsupported": [prompt], "clarification": ""}
            return {"actions": [{
                "operation": "add_transition",
                "parameters": {"transition_type": "fade_in_out", "duration": 1.0},
                "description": prompt,
            }], "unsupported": [], "clarification": ""}

    monkeypatch.setattr(plan_service_module, "OllamaInstructionAdapter", FakeOllama)
    plan = plan_service.generate_plan(mock_timeline.media_id, "Make it dramatic and add a fade at the end")

    assert calls == ["primary-model", "coder-model"]
    assert plan["operations_count"] == 1
    assert plan["operations"][0]["type"] == "add_transition"
    assert plan["operations"][0]["validation_status"] == "valid"


def test_ollama_drops_unrequested_caption_changes(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "ollama")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_MODEL", "primary-model")
    calls = []

    class FakeOllama:
        def plan_prompt(self, prompt, context):
            calls.append(prompt)
            return {"actions": [
                {"operation": "color_grade", "parameters": {"preset": "cinematic"}, "description": prompt},
                {"operation": "set_caption_style", "parameters": {"font_family": "Arial", "font_size": 24}, "description": "Change the captions"},
            ], "unsupported": [], "clarification": ""}

    monkeypatch.setattr(plan_service_module, "OllamaInstructionAdapter", FakeOllama)
    plan = plan_service.generate_plan(mock_timeline.media_id, "Make this warmer and more cinematic")

    assert len(calls) == 1
    assert [op["type"] for op in plan["operations"]] == ["color_grade"]


def test_ollama_ignores_redundant_unsupported_and_non_question_commentary(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "ollama")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_MODEL", "primary-model")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_FALLBACK_MODELS", "backup-model")
    calls = []

    class FakeOllama:
        def __init__(self, model=None):
            self.model = model or "primary-model"

        def plan_prompt(self, prompt, context):
            calls.append(self.model)
            return {"actions": [{
                "operation": "color_grade",
                "parameters": {"preset": "cinematic"},
                "description": "Apply cinematic grade for warmer video color",
            }], "unsupported": [prompt], "clarification": "This preset may not be available in all editors."}

    monkeypatch.setattr(plan_service_module, "OllamaInstructionAdapter", FakeOllama)
    plan = plan_service.generate_plan(mock_timeline.media_id, "Make it warmer and more cinematic")

    assert calls == ["primary-model"]
    assert len(plan["operations"]) == 1
    assert plan["operations"][0]["type"] == "color_grade"
    assert plan["operations"][0]["validation_status"] == "valid"


def test_ollama_cannot_turn_unrelated_request_into_a_color_edit(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "ollama")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_MODEL", "primary-model")

    class FakeOllama:
        def plan_prompt(self, prompt, context):
            return {"actions": [{
                "operation": "color_grade",
                "parameters": {"preset": "cinematic"},
                "description": "Apply cinematic color grading",
            }], "unsupported": [], "clarification": ""}

    monkeypatch.setattr(plan_service_module, "OllamaInstructionAdapter", FakeOllama)
    plan = plan_service.generate_plan(mock_timeline.media_id, "fly to the moon and invert physics entirely")

    assert plan["operations"] == []


def test_ollama_unsupported_tool_is_reported_and_cannot_be_approved(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "ollama")

    class FakeOllama:
        def plan_prompt(self, prompt, context):
            return {
                "actions": [{"operation": "object_removal", "parameters": {}, "description": "Remove the camera operator"}],
                "unsupported": ["Object removal is not implemented by the current renderer."],
                "clarification": "",
            }

    monkeypatch.setattr(plan_service_module, "OllamaInstructionAdapter", FakeOllama)
    plan = plan_service.generate_plan(mock_timeline.media_id, "erase the camera operator behind me")

    assert len(plan["operations"]) == 2
    assert all(op["validation_status"] == "unsupported" for op in plan["operations"])
    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])
    assert result["status"] == "unsupported"
    assert result["applied_count"] == 0
    assert result["skipped_count"] == 2


def test_mixed_plan_applies_supported_edits_and_reports_unsupported_ones(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "ollama")

    class FakeOllama:
        def plan_prompt(self, prompt, context):
            return {
                "actions": [
                    {"operation": "color_grade", "parameters": {"preset": "grayscale"}, "description": "Make it monochrome"},
                    {"operation": "object_removal", "parameters": {}, "description": "Remove the camera operator"},
                ],
                "unsupported": ["Object removal is not available in the current engine."],
                "clarification": "",
            }

    monkeypatch.setattr(plan_service_module, "OllamaInstructionAdapter", FakeOllama)
    plan = plan_service.generate_plan(mock_timeline.media_id, "Make this monochrome and erase the camera operator")
    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])

    assert result["status"] == "partial"
    assert result["applied_count"] == 1
    assert result["skipped_count"] == 2
    assert any("object removal" in item.lower() for item in result["skipped_operations"])
    assert engine.timeline.video_effects.color_grade == "grayscale"


@pytest.mark.parametrize(
    "prompt",
    [
        "change into black white",
        "Apply black and white color preset",
        "Turn this video black & white",
        "Make the clip monochrome",
        "Apply grayscale",
    ],
)
def test_black_and_white_color_grade_aliases_render_as_grayscale(mock_timeline, prompt):
    prop = InstructionParser().parse_instruction(prompt, mock_timeline)
    assert prop.operation_type == OperationType.COLOR_GRADE
    assert prop.parameters["preset"] == "grayscale"

def test_smooth_fade_transitions(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Add a smooth fade-in and fade-out.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.ADD_TRANSITION
    assert prop.parameters["type"] == "fade_in_out"


def test_fade_in_and_out_plan_applies_when_ollama_is_unavailable(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "auto")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_MODEL", "test-model")

    def unexpected_model_call(*args, **kwargs):
        pytest.fail("A clear paired fade should not need Ollama")

    monkeypatch.setattr(plan_service_module.OllamaInstructionAdapter, "plan_prompt", unexpected_model_call)
    plan = plan_service.generate_plan(mock_timeline.media_id, "Add a smooth fade-in and fade-out.")
    assert plan["instruction_provider"] == "rules_fast_path"
    assert len(plan["operations"]) == 1
    operation = plan["operations"][0]
    assert operation["type"] == "add_transition"
    assert operation["parameters"]["transition_type"] == "fade_in_out"
    assert operation["validation_status"] == "valid"

    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])
    assert result["status"] == "applied"
    assert engine.timeline.video_effects.fade_in_duration == 1.0
    assert engine.timeline.video_effects.fade_out_duration == 1.0


def test_clip_crossfade_prompt(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Apply a crossfade between clips of 0.75 seconds.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.ADD_TRANSITION
    assert prop.parameters["transition_type"] == "crossfade"
    assert prop.parameters["duration"] == 0.75

def test_audio_ducking_prompt(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Lower the music when someone speaks.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.AUDIO_DUCKING
    assert prop.parameters == {"enabled": True, "attenuation_db": 12.0}


def test_audio_ducking_plan_applies_without_ollama(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "auto")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_MODEL", "test-model")

    def unexpected_model_call(*args, **kwargs):
        pytest.fail("A clear audio-ducking request should not need Ollama")

    monkeypatch.setattr(plan_service_module.OllamaInstructionAdapter, "plan_prompt", unexpected_model_call)
    plan = plan_service.generate_plan(mock_timeline.media_id, "Lower the music when someone speaks.")
    assert plan["instruction_provider"] == "rules_fast_path"
    assert len(plan["operations"]) == 1
    operation = plan["operations"][0]
    assert operation["type"] == "audio_ducking"
    assert operation["parameters"] == {"enabled": True, "attenuation_db": 12.0}
    assert operation["validation_status"] == "valid"

    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])
    assert result["status"] == "applied"
    assert engine.timeline.video_effects.audio_ducking is True


def test_mute_time_range_plan_applies_with_normalized_time_fields(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "auto")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_MODEL", "test-model")

    plan = plan_service.generate_plan(mock_timeline.media_id, "mute from 20 to 30 s in the video")
    assert len(plan["operations"]) == 1
    operation = plan["operations"][0]
    assert operation["type"] == "mute"
    assert operation["validation_status"] == "valid"

    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])
    assert result["status"] == "applied"
    mute = engine.timeline.audio_effects.mutes[-1]
    assert mute.source_start == 20.0
    assert mute.source_end == 30.0


def test_tamil_first_ten_seconds_cut_plan_applies(mock_timeline, monkeypatch):
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(plan_service_module.timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(plan_service_module.media_service, "get_media_manifest", lambda media_id: None)
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "auto")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_MODEL", "test-model")

    plan = plan_service.generate_plan(mock_timeline.media_id, "mudhal 10 seconds cut pannu")
    assert len(plan["operations"]) == 1
    operation = plan["operations"][0]
    assert operation["type"] == "cut_range"
    assert operation["validation_status"] == "valid"

    result = plan_service.apply_plan(mock_timeline.media_id, plan["operations"])
    assert result["status"] == "applied"
    assert engine.timeline.total_output_duration == 50.0


def test_speed_tool_accepts_normalized_time_parameters():
    params = {
        "start": 10.0,
        "end": 20.0,
        "start_time": 10.0,
        "end_time": 20.0,
        "time_basis": "current_timeline",
        "speed": 1.5,
    }
    assert capability_registry.validate("speed_change", params) is None


def test_cinematic_preset_accepts_video_scope_from_planner():
    assert capability_registry.validate(
        "apply_preset", {"preset": "cinematic", "target": "video"}
    ) is None


def test_low_confidence_word_is_not_bleeped_blindly(mock_timeline, monkeypatch):
    mock_timeline.transcript.get_word_by_id("w6").confidence = 0.2
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(media_service, "get_media_manifest", lambda media_id: None)

    result = instruction_service.process_instruction(
        mock_timeline.media_id, "bleep word 'Thank'"
    )

    assert result.status.value == "rejected"
    assert result.error_code == "LOW_CONFIDENCE_TRANSCRIPT_TARGET"
    assert "Thank" in result.message
    assert not engine.timeline.audio_effects.bleeps
    assert engine.timeline.revision == mock_timeline.revision


def test_semantic_pricing_search_finds_cost_and_applies_with_reviewable_match(mock_timeline, monkeypatch):
    mock_timeline.transcript.words.append(
        TranscriptWord(id="w10", text="cost", start=10.0, end=10.4, confidence=0.95)
    )
    engine = TimelineEngine(mock_timeline)
    monkeypatch.setattr(timeline_service, "get_engine", lambda media_id: engine)
    monkeypatch.setattr(timeline_service, "save_timeline", lambda timeline: "test-hash")
    monkeypatch.setattr(media_service, "get_media_manifest", lambda media_id: None)

    proposal = InstructionParser().parse_instruction(
        "Remove the part about pricing", mock_timeline
    )
    assert proposal.parameters["word_ids"] == ["w10"]
    assert proposal.parameters["target_words"][0].text == "cost"
    result = instruction_service.process_proposal(mock_timeline.media_id, proposal)

    assert result.status.value == "applied"
    assert result.operations[0].parameters["word_ids"] == ["w10"]
    assert engine.timeline.total_output_duration == pytest.approx(59.6)


def test_semantic_pricing_search_asks_when_multiple_synonyms_match(mock_timeline):
    mock_timeline.transcript.words.extend([
        TranscriptWord(id="w10", text="cost", start=10.0, end=10.4),
        TranscriptWord(id="w11", text="fees", start=20.0, end=20.4),
    ])

    with pytest.raises(ClarificationNeeded) as exc_info:
        InstructionParser().parse_instruction(
            "Remove the part about pricing", mock_timeline
        )

    assert len(exc_info.value.options) == 2
    assert "cost" in exc_info.value.question or "pricing" in exc_info.value.question

def test_blur_background_region(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Blur the selected background region if supported by the available processing pipeline.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.BLUR_REGION

def test_educational_preset(mock_timeline):
    parser = InstructionParser()
    prop = parser.parse_instruction("Make this look like an educational video.", mock_timeline)
    assert prop is not None
    assert prop.operation_type == OperationType.APPLY_PRESET
    assert prop.parameters["preset"] == "educational"

def test_undo_and_restore_relative_prompts(mock_timeline):
    parser = InstructionParser()
    prop_undo = parser.parse_instruction("Undo the last change.", mock_timeline)
    assert prop_undo is not None
    assert prop_undo.operation_type == OperationType.UNDO

    # Current revision is 5; restore before last three edits -> target revision 2
    prop_restore = parser.parse_instruction("Restore the version before the last three edits.", mock_timeline)
    assert prop_restore is not None
    assert prop_restore.operation_type == OperationType.RESTORE_REVISION
    assert prop_restore.parameters["target_revision"] == 2


def test_rule_prompt_split_preserves_quotes_and_decimal_times():
    clauses = plan_service._split_compound_prompt(
        'Remove silence longer than 1.5 seconds, then add opening title "Adventure and Beyond" and generate captions'
    )
    assert clauses == [
        "Remove silence longer than 1.5 seconds",
        'add opening title "Adventure and Beyond"',
        "generate captions",
    ]


def test_rule_prompt_split_keeps_um_and_uh_together():
    assert plan_service._split_compound_prompt("remove um and uh") == ["remove um and uh"]


def test_generate_subtitles_is_not_mistaken_for_a_title_card(mock_timeline, monkeypatch):
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: SimpleNamespace(timeline=mock_timeline))
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "rules")

    plan = plan_service.generate_plan("test-media", "Generate subtitles")

    assert [operation["type"] for operation in plan["operations"]] == ["generate_captions"]


@pytest.mark.parametrize("prompt", ["Generate English subtitles.", "Generate subtitles in English."])
def test_generate_english_subtitles_is_recognized_when_transcript_is_english(mock_timeline, monkeypatch, prompt):
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: SimpleNamespace(timeline=mock_timeline))
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "rules")

    plan = plan_service.generate_plan("test-media", prompt)

    operation = plan["operations"][0]
    assert operation["type"] == "generate_captions"
    assert operation["parameters"]["language"] == "en"
    assert operation["validation_status"] == "valid"


def test_english_subtitle_request_does_not_claim_to_translate_non_english_transcript(mock_timeline, monkeypatch):
    mock_timeline.transcript.language = "ta"
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: SimpleNamespace(timeline=mock_timeline))
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "rules")

    plan = plan_service.generate_plan("test-media", "Generate English subtitles")

    operation = plan["operations"][0]
    assert operation["type"] == "generate_captions"
    assert operation["validation_status"] == "unsupported"
    assert "translation is not available" in operation["validation_message"]


def test_auto_uses_complete_rules_plan_without_needing_local_ai(mock_timeline, monkeypatch):
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: SimpleNamespace(timeline=mock_timeline))
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "auto")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_MODEL", "test-model")

    def unavailable(self, instruction, context):
        raise plan_service_module.OllamaProviderError("Ollama is offline")

    monkeypatch.setattr(plan_service_module.OllamaInstructionAdapter, "plan_prompt", unavailable)
    plan = plan_service.generate_plan("test-media", "Cut from 1 to 3 seconds and generate captions")

    assert plan["instruction_provider"] == "rules_fast_path"
    assert plan["provider_notice"] is None
    assert [operation["type"] for operation in plan["operations"]] == ["cut_range", "generate_captions"]
    assert all(operation["validation_status"] == "valid" for operation in plan["operations"])


def test_auto_fallback_understands_silence_and_long_pauses_as_one_edit(mock_timeline, monkeypatch):
    monkeypatch.setattr(plan_service_module.timeline_service, "get_engine", lambda media_id: SimpleNamespace(timeline=mock_timeline))
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "auto")
    monkeypatch.setattr(plan_service_module.settings, "OLLAMA_MODEL", "test-model")

    def unavailable(self, instruction, context):
        raise plan_service_module.OllamaProviderError("Ollama is offline")

    monkeypatch.setattr(plan_service_module.OllamaInstructionAdapter, "plan_prompt", unavailable)
    plan = plan_service.generate_plan("test-media", "Remove silence and long pauses.")

    assert plan["instruction_provider"] == "rules_fallback"
    assert plan["operations_count"] == 1
    assert plan["operations"][0]["type"] == "remove_silence"
    assert plan["operations"][0]["validation_status"] == "valid"
    assert plan["operations"][0]["parameters"]["min_silence_s"] == 1.0
