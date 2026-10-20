"""Discoverable, validated editing tools exposed to AI planners.

This registry describes operations that have deterministic handlers in
InstructionService. It is deliberately independent of prompt wording: the
planner sees the current tool list, and the executor still validates every
proposal before calling the timeline engine.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable

from app.models.operation import OperationType


@dataclass(frozen=True)
class EditingCapability:
    operation: OperationType
    description: str
    parameter_hints: str
    parameter_keys: tuple[str, ...] = ()
    required_parameters: tuple[str, ...] = ()

    def as_tool(self) -> Dict[str, Any]:
        return {
            "name": self.operation.value,
            "description": self.description,
            "parameters": self.parameter_hints,
        }


class CapabilityRegistry:
    """Registry of operations with real timeline-engine execution handlers."""

    def __init__(self, capabilities: Iterable[EditingCapability] | None = None):
        self._capabilities: Dict[str, EditingCapability] = {}
        for capability in capabilities or self._built_in_capabilities():
            self.register(capability)

    @staticmethod
    def _built_in_capabilities() -> Iterable[EditingCapability]:
        # Keep this list aligned with InstructionService._execute_proposal.
        # Adding a capability requires a deterministic engine handler as well.
        specs = {
            OperationType.CUT_RANGE: ("Remove a source or timeline interval.", "start, end, time_basis"),
            OperationType.KEEP_RANGE: ("Keep only a selected interval.", "start, end, time_basis"),
            OperationType.REMOVE_PHRASE: ("Remove a spoken phrase found in the transcript.", "text, target_words, word_ids"),
            OperationType.REORDER_SECTIONS: ("Reorder existing timeline segments by their stable IDs.", "new_segment_order"),
            OperationType.SPEED_CHANGE: ("Change playback speed for a time range.", "start, end, speed"),
            OperationType.MUTE: ("Mute audio over a time range or transcript words.", "start, end, word_ids"),
            OperationType.BLEEP: ("Replace audio over a time range with a censor tone.", "start, end, frequency_hz, word_ids"),
            OperationType.ADD_CAPTION: ("Add a caption anchored to transcript words.", "text, anchor_word_ids"),
            OperationType.ADD_TEXT_OVERLAY: ("Render text over a selected part of the video.", "text, position, source_start, source_end"),
            OperationType.GENERATE_CAPTIONS: ("Generate word-aligned captions from the existing transcript.", "language"),
            OperationType.REMOVE_FILLER_WORDS: ("Remove detected filler words from the transcript timeline.", ""),
            OperationType.REMOVE_SILENCE: ("Remove silent pauses using the engine's silence detector.", "threshold_seconds, min_silence_s"),
            OperationType.ADD_BACKGROUND_MUSIC: ("Mix the available background music under the video audio.", "track_id, volume, ducking_enabled"),
            OperationType.COLOR_GRADE: ("Apply color grading parameters to the video.", "preset, brightness, contrast, saturation, gamma"),
            OperationType.SET_CAPTION_STYLE: ("Set styling for rendered subtitles.", "font_family, font_size, primary_color, outline_color, bold, vertical_position"),
            OperationType.SET_CAPTION_MODE: ("Choose sentence or word-highlight caption timing.", "mode, highlight_color"),
            OperationType.ADD_TRANSITION: ("Add supported fades or crossfades between retained clips.", "transition_type, duration"),
            OperationType.SET_ASPECT_RATIO: ("Set the output canvas aspect ratio.", "aspect_ratio"),
            OperationType.CREATE_REEL: ("Create a social-media reel with a target duration and aspect ratio.", "target_duration_s, aspect_ratio"),
            OperationType.BLUR_REGION: ("Apply a box blur to the full output video.", "blur_radius"),
            OperationType.APPLY_PRESET: ("Apply a built-in video or reel preset.", "preset"),
            OperationType.AUDIO_NORMALIZE: ("Normalize output audio loudness.", "enabled"),
            OperationType.AUDIO_DUCKING: ("Enable or configure speech-aware audio ducking.", "enabled, attenuation_db"),
            OperationType.AUDIO_DENOISE: ("Reduce background noise in source audio.", "enabled, reduction_db"),
            OperationType.VIDEO_TRANSFORM: ("Rotate or mirror the video.", "rotation_degrees, horizontal_flip, vertical_flip"),
            OperationType.SPLIT_CLIP: ("Split a timeline segment at a timestamp.", "split_time, time_basis"),
            OperationType.DUPLICATE_CLIP: ("Duplicate a timeline clip or segment.", "segment_id, index"),
            OperationType.UNDO: ("Undo the latest timeline change.", ""),
            OperationType.REDO: ("Redo the latest undone timeline change.", ""),
            OperationType.RESTORE_EDIT: ("Restore a prior edit or timeline revision.", "target_operation_id, target_revision"),
        }
        aliases = {
            OperationType.GENERATE_CAPTIONS: ("language",),
            OperationType.CUT_RANGE: ("start", "end", "start_time", "end_time", "time_basis"),
            OperationType.KEEP_RANGE: ("start", "end", "start_time", "end_time", "time_basis"),
            OperationType.SPLIT_CLIP: ("split_time", "time", "at", "time_basis"),
            OperationType.DUPLICATE_CLIP: ("segment_id", "clip_id", "index"),
            OperationType.COLOR_GRADE: ("vignette",),
            OperationType.REORDER_SECTIONS: ("new_segment_order",),
            OperationType.REMOVE_PHRASE: ("text", "phrase", "target_words", "word_ids", "start", "end", "semantic_search"),
            OperationType.SPEED_CHANGE: ("start", "end", "start_time", "end_time", "speed", "target", "time_basis", "ending_duration"),
            OperationType.MUTE: ("start", "end", "start_time", "end_time", "time_basis", "word_ids", "phrase", "text", "word"),
            OperationType.BLEEP: ("start", "end", "start_time", "end_time", "time_basis", "word_ids", "phrase", "text", "word", "frequency_hz"),
            OperationType.ADD_CAPTION: ("text", "anchor_word_ids", "anchor_phrase"),
            OperationType.ADD_TRANSITION: ("transition_type", "type", "duration"),
            OperationType.CREATE_REEL: ("target_duration",),
            OperationType.APPLY_PRESET: ("target",),
        }
        def build():
            for op, (description, params) in specs.items():
                keys = tuple(dict.fromkeys([*(key.strip() for key in params.split(",") if key.strip()), *aliases.get(op, ())]))
                required = ("start", "end") if op in (OperationType.CUT_RANGE, OperationType.KEEP_RANGE) else ()
                if op == OperationType.SPEED_CHANGE:
                    required = ("start", "end", "speed")
                elif op in (OperationType.MUTE, OperationType.BLEEP):
                    # Either a valid range or transcript target is accepted.
                    required = ()
                elif op == OperationType.ADD_CAPTION:
                    required = ("text",)
                elif op == OperationType.ADD_TEXT_OVERLAY:
                    required = ("text",)
                elif op == OperationType.REORDER_SECTIONS:
                    required = ("new_segment_order",)
                elif op == OperationType.SPLIT_CLIP:
                    required = ("split_time",)
                yield EditingCapability(op, description, params, keys, required)
        return build()

    def register(self, capability: EditingCapability) -> None:
        self._capabilities[capability.operation.value] = capability

    def get(self, operation: str) -> EditingCapability | None:
        return self._capabilities.get(operation.strip().lower())

    def tools(self) -> list[Dict[str, Any]]:
        return [capability.as_tool() for capability in self._capabilities.values()]

    def parameter_json_schema(self, operation: str | None = None) -> Dict[str, Any]:
        """Build a typed schema for one tool, or a compatibility union if omitted."""
        strings = {
            "time_basis", "text", "position", "track_id", "preset", "font_family",
            "primary_color", "outline_color", "vertical_position", "mode", "highlight_color",
            "transition_type", "type", "aspect_ratio", "language", "target_operation_id",
            "phrase", "word", "anchor_phrase", "target", "segment_id", "clip_id",
        }
        booleans = {"ducking_enabled", "bold", "enabled", "horizontal_flip", "vertical_flip", "apply_to_existing", "semantic_search", "vignette"}
        string_arrays = {"word_ids", "anchor_word_ids", "new_segment_order"}
        capability = self.get(operation) if operation else None
        fields = (
            set(capability.parameter_keys)
            if capability
            else {key for item in self._capabilities.values() for key in item.parameter_keys}
        )
        properties: Dict[str, Any] = {}
        for key in sorted(fields):
            if key in strings or key.endswith("_id"):
                properties[key] = {"type": "STRING"}
            elif key in booleans:
                properties[key] = {"type": "BOOLEAN"}
            elif key in string_arrays:
                properties[key] = {"type": "ARRAY", "items": {"type": "STRING"}}
            elif key == "target_words":
                properties[key] = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                    "id": {"type": "STRING"}, "text": {"type": "STRING"},
                    "start": {"type": "NUMBER"}, "end": {"type": "NUMBER"},
                }}}
            else:
                properties[key] = {"type": "NUMBER"}
        schema = {"type": "OBJECT", "properties": properties, "additionalProperties": False}
        if capability and capability.required_parameters:
            schema["required"] = list(capability.required_parameters)
        return schema

    def validate(self, operation: str, parameters: Any) -> str | None:
        if self.get(operation) is None:
            return f"No deterministic editing tool is registered for '{operation}'."
        if not isinstance(parameters, dict):
            return "Operation parameters must be a JSON object."
        # Reject nested executable-looking values and non-finite numbers.
        def safe(value: Any) -> bool:
            if isinstance(value, dict):
                return all(isinstance(k, str) and safe(v) for k, v in value.items())
            if isinstance(value, list):
                return all(safe(item) for item in value)
            if isinstance(value, float):
                return value == value and abs(value) != float("inf")
            return value is None or isinstance(value, (str, int, float, bool))
        if not safe(parameters):
            return "Operation parameters contain unsupported values."
        capability = self.get(operation)
        unknown = set(parameters) - set(capability.parameter_keys)
        if unknown:
            return f"Unsupported parameter(s) for '{operation}': {', '.join(sorted(unknown))}."
        schema = self.parameter_json_schema()["properties"]
        for key, value in parameters.items():
            if value is None:
                continue
            expected = schema[key]["type"]
            valid = (
                isinstance(value, str) if expected == "STRING" else
                isinstance(value, bool) if expected == "BOOLEAN" else
                isinstance(value, list) if expected == "ARRAY" else
                isinstance(value, (int, float)) and not isinstance(value, bool) if expected == "NUMBER" else
                False
            )
            if not valid:
                return f"Parameter '{key}' for '{operation}' must be {expected.lower()}."
            if expected == "ARRAY":
                item_type = schema[key].get("items", {}).get("type")
                if item_type == "STRING" and not all(isinstance(item, str) for item in value):
                    return f"Every item in '{key}' for '{operation}' must be a string."
                if key == "target_words":
                    for item in value:
                        if not isinstance(item, dict) or set(item) - {"id", "text", "start", "end"}:
                            return "Each target_words item must contain only id, text, start, and end fields."
                        if any(k in item and not isinstance(item[k], (int, float)) for k in ("start", "end")):
                            return "target_words start and end values must be numeric."
        missing = [key for key in capability.required_parameters if parameters.get(key) is None]
        if missing:
            return f"'{operation}' requires: {', '.join(missing)}."
        if "start" in parameters and "end" in parameters:
            if parameters["start"] is not None and parameters["end"] is not None and parameters["start"] >= parameters["end"]:
                return "The operation start time must be earlier than its end time."
        if capability.operation == OperationType.SPEED_CHANGE and "speed" in parameters:
            if not 0.05 <= parameters["speed"] <= 10:
                return "Playback speed must be between 0.05x and 10x."
        if capability.operation in (OperationType.MUTE, OperationType.BLEEP):
            has_range = parameters.get("start") is not None and parameters.get("end") is not None
            has_phrase = bool(parameters.get("phrase") or parameters.get("text") or parameters.get("word") or parameters.get("word_ids"))
            if not has_range and not has_phrase:
                return f"'{operation}' requires a time range or transcript phrase."
        return None


capability_registry = CapabilityRegistry()
