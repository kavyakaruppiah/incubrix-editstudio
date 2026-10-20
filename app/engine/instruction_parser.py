import re
import uuid
from typing import Any, Dict, List, Optional, Tuple
from app.engine.parser_registry import ParserRegistry, parse_timestamp
from app.core.time_parser import TICKS_PER_SECOND, duration_ticks, parse_time_expression
from app.models.operation import ClarificationOption, OperationProposal, OperationType
from app.models.timeline import Timeline
from app.models.transcript import Transcript, TranscriptWord, normalize_text


class ClarificationNeeded(Exception):
    def __init__(self, question: str, options: List[ClarificationOption]):
        self.question = question
        self.options = options
        super().__init__(question)


class InstructionParser:
    def __init__(self):
        self.registry = ParserRegistry()
        self._register_rules()

    def _register_rules(self):
        # 1. Cut range
        # e.g., "cut from 00:05 to 00:10", "cut between 5s and 10s", "cut 2 to 5", "trim 2 to 5", "cut 0-5"
        self.registry.register(
            OperationType.CUT_RANGE,
            r"(?:cut|delete|remove|trim)\s+(?:output\s+)?(?:from\s+|between\s+)?(?P<start>[\d:\.]+s?)\s*(?:to|and|-)\s*(?P<end>[\d:\.]+s?)",
            lambda m: {
                "start": parse_timestamp(m.group("start")),
                "end": parse_timestamp(m.group("end")),
                "time_basis": "current_timeline" if "output" in m.group(0).lower() else "source",
            },
        )
        # Cut first N seconds e.g. "cut first 5 seconds", "remove first 3s"
        self.registry.register(
            OperationType.CUT_RANGE,
            r"(?:cut|delete|remove|trim)\s+(?:the\s+)?first\s+(?P<dur>[\d:\.]+s?)(?:\s*(?:s|sec|seconds))?",
            lambda m: {
                "start": 0.0,
                "end": parse_timestamp(m.group("dur")),
                "time_basis": "source",
            },
        )
        # Cut last N seconds e.g. "cut last 5 seconds", "trim last 3s"
        self.registry.register(
            OperationType.CUT_RANGE,
            r"(?:cut|delete|remove|trim)\s+(?:the\s+)?last\s+(?P<dur>[\d:\.]+s?)(?:\s*(?:s|sec|seconds))?",
            lambda m: {
                "start": -parse_timestamp(m.group("dur")),
                "end": 999999.0,
                "time_basis": "current_timeline",
            },
        )

        # 2. Keep range
        # e.g., "keep only from 00:10 to 00:30", "keep between 5 and 15s", "keep 2 to 8"
        self.registry.register(
            OperationType.KEEP_RANGE,
            r"keep\s+(?:only\s+)?(?:from\s+|between\s+)?(?P<start>[\d:\.]+s?)\s*(?:to|and|-)\s*(?P<end>[\d:\.]+s?)",
            lambda m: {
                "start": parse_timestamp(m.group("start")),
                "end": parse_timestamp(m.group("end")),
                "time_basis": "source",
            },
        )
        # Keep first N seconds e.g. "keep first 10 seconds", "keep first 5s"
        self.registry.register(
            OperationType.KEEP_RANGE,
            r"keep\s+(?:only\s+)?(?:the\s+)?first\s+(?P<dur>[\d:\.]+s?)(?:\s*(?:s|sec|seconds))?",
            lambda m: {
                "start": 0.0,
                "end": parse_timestamp(m.group("dur")),
                "time_basis": "source",
            },
        )

        # 3. Remove phrase
        # e.g., "remove phrase 'hello world'", "cut 'thank you'", "remove word um"
        self.registry.register(
            OperationType.REMOVE_PHRASE,
            r"(?:remove|cut|delete)\s+(?:the\s+)?(?:part|section|bit)\s+about\s+(?P<topic>[a-zA-Z0-9_\-]+)",
            lambda m: {"phrase": m.group("topic").strip(), "semantic_search": True},
        )
        self.registry.register(
            OperationType.REMOVE_PHRASE,
            r"(?:remove|cut|delete)\s+(?:the\s+)?(?:(?:first|second|last|1st|2nd)\s+)?(?:phrase\s+|word\s+|words\s+)?[\"'](?P<phrase>[^\"']+)[\"']",
            lambda m: {"phrase": m.group("phrase").strip()},
        )
        self.registry.register(
            OperationType.REMOVE_PHRASE,
            r"(?:remove|cut|delete)\s+(?:the\s+)?(?:(?:first|second|last|1st|2nd)\s+)?(?:phrase\s+|word\s+|words\s+)(?P<phrase_raw>[a-zA-Z0-9_\-]+)",
            lambda m: {"phrase": m.group("phrase_raw").strip()},
        )

        # 4. Reorder sections
        # e.g., "reorder segments seg_1, seg_2", "swap segments"
        self.registry.register(
            OperationType.REORDER_SECTIONS,
            r"(?:reorder|swap)\s+segments?\s+(?P<order>[a-zA-Z0-9_\-,\s]+)",
            lambda m: {
                "new_segment_order": [x.strip() for x in m.group("order").replace(",", " ").split() if x.strip()]
            },
        )

        # 5. Speed up
        # e.g., "speed up from 10s to 20s by 1.5x", "speed up 0 to 5 by 2"
        self.registry.register(
            OperationType.SPEED_CHANGE,
            r"speed\s+up\s+(?:the\s+)?(?:final|last)\s+(?P<dur>[\d:.]+)\s*(?:s|sec|seconds?)?\s+(?:by|to)\s+(?P<speed>[\d.]+)x?",
            lambda m: {
                "start": 0.0,
                "end": 0.0,
                "speed": float(m.group("speed")),
                "target": "ending",
                "ending_duration": parse_timestamp(m.group("dur")),
            },
        )
        self.registry.register(
            OperationType.SPEED_CHANGE,
            r"speed\s+up\s+(?:from\s+)?(?P<start>[\d:\.]+s?)\s+(?:to|-)\s+(?P<end>[\d:\.]+s?)\s+(?:by|to)\s+(?P<speed>[\d\.]+)x?",
            lambda m: {
                "start": parse_timestamp(m.group("start")),
                "end": parse_timestamp(m.group("end")),
                "speed": float(m.group("speed")),
            },
        )
        # Whole video speed up e.g. "speed up 2x", "make it 2x faster"
        self.registry.register(
            OperationType.SPEED_CHANGE,
            r"(?:speed\s+up|speed|make\s+it\s+faster)\s+(?:video\s+)?(?:by\s+|to\s+)?(?P<speed>[\d\.]+)x?",
            lambda m: {
                "start": 0.0,
                "end": 999999.0,
                "speed": float(m.group("speed")),
            },
        )
        self.registry.register(
            OperationType.SPEED_CHANGE,
            r"make\s+(?:it|the\s+video)\s+(?P<speed>[\d\.]+)x?\s+faster",
            lambda m: {"start": 0.0, "end": 999999.0, "speed": float(m.group("speed"))},
        )

        # 6. Slow down
        # e.g., "slow down from 15s to 25s to 0.75x", "slow down 5 to 10 to 0.5"
        self.registry.register(
            OperationType.SPEED_CHANGE,
            r"slow\s+down\s+(?:from\s+)?(?P<start>[\d:\.]+s?)\s+(?:to|-)\s+(?P<end>[\d:\.]+s?)\s+(?:by|to)\s+(?P<speed>[\d\.]+)x?",
            lambda m: {
                "start": parse_timestamp(m.group("start")),
                "end": parse_timestamp(m.group("end")),
                "speed": float(m.group("speed")),
            },
        )
        # Whole video slow down e.g. "slow down to 0.5x"
        self.registry.register(
            OperationType.SPEED_CHANGE,
            r"slow\s+down\s+(?:video\s+)?(?:by\s+|to\s+)?(?P<speed>[\d\.]+)x?",
            lambda m: {
                "start": 0.0,
                "end": 999999.0,
                "speed": float(m.group("speed")),
            },
        )

        # 7. Mute range, word, or whole video
        # e.g., "mute from 12s to 15s", "mute 2 to 4", "mute word 'confidential'", "mute 'hello'", "mute video"
        self.registry.register(
            OperationType.MUTE,
            r"mute\s+(?:from\s+|between\s+)?(?P<start>[\d:\.]+s?)\s+(?:to|and|-)\s+(?P<end>[\d:\.]+s?)",
            lambda m: {
                "start": parse_timestamp(m.group("start")),
                "end": parse_timestamp(m.group("end")),
            },
        )
        self.registry.register(
            OperationType.MUTE,
            r"mute\s+(?:the\s+)?(?:word\s+|phrase\s+)?[\"'](?P<phrase>[^\"']+)[\"']",
            lambda m: {"phrase": m.group("phrase").strip()},
        )
        self.registry.register(
            OperationType.MUTE,
            r"^mute(?:\s+(?:the\s+)?(?:video|audio|all))?$",
            lambda m: {
                "start": 0.0,
                "end": 999999.0,
            },
        )

        # 8. Bleep range or word
        # e.g., "bleep from 5s to 6s", "bleep 2 to 4", "bleep word 'damn'", "bleep 'curse'"
        self.registry.register(
            OperationType.BLEEP,
            r"bleep\s+(?:from\s+|between\s+)?(?P<start>[\d:\.]+s?)\s+(?:to|and|-)\s+(?P<end>[\d:\.]+s?)",
            lambda m: {
                "start": parse_timestamp(m.group("start")),
                "end": parse_timestamp(m.group("end")),
                "frequency_hz": 1000.0,
            },
        )
        self.registry.register(
            OperationType.BLEEP,
            r"bleep\s+(?:the\s+)?(?:word\s+|phrase\s+)?[\"'](?P<phrase>[^\"']+)[\"']",
            lambda m: {"phrase": m.group("phrase").strip(), "frequency_hz": 1000.0},
        )

        # 9. Add caption
        # e.g., "add caption 'Important Notice' at words 'pay attention'", "caption 'hello' at 'world'"
        self.registry.register(
            OperationType.ADD_CAPTION,
            r"(?:add\s+)?caption\s+[\"'](?P<text>[^\"']+)[\"']\s+(?:at\s+(?:words?\s+|phrase\s+)?|for\s+)[\"'](?P<anchor>[^\"']+)[\"']",
            lambda m: {
                "text": m.group("text").strip(),
                "anchor_phrase": m.group("anchor").strip(),
            },
        )

        # 10. Add text overlay
        # e.g., "add text overlay 'Welcome' at top from 0s to 5s", "add overlay 'Subscribe' at bottom from 10s to 15s"
        self.registry.register(
            OperationType.ADD_TEXT_OVERLAY,
            r"(?:add\s+)?(?:text\s+)?overlay\s+[\"'](?P<text>[^\"']+)[\"']\s+(?:at\s+(?P<pos>top|bottom|center)\s+)?(?:from\s+)?(?P<start>[\d:\.]+s?)\s+(?:to|-)\s+(?P<end>[\d:\.]+s?)",
            lambda m: {
                "text": m.group("text").strip(),
                "position": m.group("pos") or "bottom",
                "source_start": parse_timestamp(m.group("start")),
                "source_end": parse_timestamp(m.group("end")),
            },
        )
        # Natural title-card phrasing should use the same real text-overlay renderer.
        # The reviewed-plan path can infer richer timing; direct commands get a
        # safe four-second opening card by default.
        self.registry.register(
            OperationType.ADD_TEXT_OVERLAY,
            r"(?:add|create|show|put|insert)\s+(?:(?:a|an|the)\s+)?(?:(?:opening|intro(?:duction)?|beginning)\s+)?title\s+card(?:\s+(?:saying|reading|called|named|with\s+(?:the\s+)?text)\s*)?\s*[\"'](?P<text>[^\"']+)[\"']",
            lambda m: {
                "text": m.group("text").strip(),
                "position": "center",
                "source_start": 0.0,
                "source_end": 4.0,
            },
        )

        # 11. Subtitle styling: Clean subtitles with white bold font and black outline
        self.registry.register(
            OperationType.SET_CAPTION_STYLE,
            r"(?:add|use|apply)\s+(?:clean\s+)?(?:subtitles|captions)\s+with\s+(?:a\s+)?(?P<col>\w+)\s+(?P<weight>bold)?\s*fonts?(?:\s+and\s+(?:a\s+)?(?P<out>\w+)\s+outline)?",
            lambda m: {
                "primary_color": "#FFFFFF" if "white" in (m.group("col") or "white").lower() else "&H00FFFFFF",
                "outline_color": "#000000" if "black" in (m.group("out") or "black").lower() else "&H00FFFFFF",
                "outline_width": 2,
                "bold": bool(m.group("weight")) or True,
                "font_size": 28,
            },
        )
        self.registry.register(
            OperationType.SET_CAPTION_STYLE,
            r"apply\s+(?:the\s+)?(?:same\s+)?caption\s+style\s+to\s+(?:the\s+)?(?:entire\s+video|all|video)",
            lambda m: {"apply_to_existing": True},
        )

        # 12. Karaoke active word highlighting
        self.registry.register(
            OperationType.SET_CAPTION_MODE,
            r"(?:highlight\s+(?:each\s+spoken\s+word|words?)\s+(?:in\s+(?P<color>\w+)\s+)?as\s+it\s+is\s+spoken|karaoke\s*(?:captions?|subtitles?|mode)?)",
            lambda m: {
                "mode": "karaoke",
                "highlight_color": "#FFFF00",
                "karaoke_color": "&H0000FFFF" if not m.group("color") or "yellow" in m.group("color").lower() else "&H0000FFFF",
            },
        )

        # 13. Generate captions / Subtitles
        # e.g., "generate captions", "add captions", "captions", "subtitles", "add subtitles", "auto caption"
        self.registry.register(
            OperationType.GENERATE_CAPTIONS,
            r"^(?:generate|create|add|auto)?\s*(?:(?P<language>english)\s+)?(?:word-aligned\s+)?(?:captions|subtitles|caption)(?:\s+this)?(?:\s+for\s+(?:the\s+)?(?:video|transcript|audio))?(?:\s+from\s+(?:the\s+)?transcript)?(?:\s+in\s+(?P<language_after>english))?[\.\!]?$",
            lambda m: {"language": "en"} if (m.group("language") or m.group("language_after")) else {},
        )

        # 14. Remove filler words
        # e.g., "remove filler words", "clean up filler words", "remove fillers", "cut fillers", "remove um and uh"
        self.registry.register(
            OperationType.REMOVE_FILLER_WORDS,
            r"(?:remove|delete|clean\s+up|clean|cut)\s+(?:all\s+)?(?:filler\s+words?|fillers|um\s+and\s+uh|ums\s+and\s+uhs|um|uh)",
            lambda m: {},
        )

        # 15. Remove silence
        # e.g., "remove silence longer than 1.5 seconds", "remove silences > 1s", "remove silence", "remove all long pauses"
        self.registry.register(
            OperationType.REMOVE_SILENCE,
            r"(?:remove|cut|delete|clean)\s+(?:all\s+)?(?:long\s+)?(?:silence(?:s)?|pauses?)(?:\s+(?:longer\s+than|>|above)\s+(?P<thresh>[\d\.]+)\s*(?:s|seconds)?)?",
            lambda m: {
                "threshold_seconds": float(m.group("thresh")) if m.group("thresh") else 1.0,
                "min_silence_s": float(m.group("thresh")) if m.group("thresh") else 1.0,
            },
        )

        # 16. Add background music
        # e.g., "add background music with ducking beneath speech", "add bgm volume 0.2"
        self.registry.register(
            OperationType.ADD_BACKGROUND_MUSIC,
            r"(?:add\s+)?(?:background\s+music|bgm)(?:\s+track\s+(?P<track>[\w\.\-]+))?(?:\s+volume\s+(?P<vol>[\d\.]+))?(?:\s+with\s+(?P<duck>ducking))?",
            lambda m: {
                "track_id": m.group("track") or "default_bgm",
                "volume": float(m.group("vol")) if m.group("vol") else 0.2,
                "ducking_enabled": bool(m.group("duck")) or True,
            },
        )

        # 17. Undo
        # e.g., "undo", "undo last edit", "undo the last change", "revert"
        self.registry.register(
            OperationType.UNDO,
            r"^(?:undo|revert)(?:\s+(?:the\s+)?(?:last\s+)?(?:edit|operation|change))?[\.\!]?$",
            lambda m: {},
        )

        # 18. Redo
        # e.g., "redo", "redo last edit"
        self.registry.register(
            OperationType.REDO,
            r"^redo(?:\s+(?:last\s+)?(?:edit|operation|change))?[\.\!]?$",
            lambda m: {},
        )

        # 19. Restore edit or Reset
        # e.g., "restore edit op_1234", "restore revision 2", "reset", "start over", "restore original"
        self.registry.register(
            OperationType.RESTORE_EDIT,
            r"restore\s+(?:edit\s+|operation\s+)?(?P<id>op_[a-zA-Z0-9]+)",
            lambda m: {"target_operation_id": m.group("id")},
        )
        self.registry.register(
            OperationType.RESTORE_EDIT,
            r"restore\s+revision\s+(?P<rev>\d+)",
            lambda m: {"target_revision": int(m.group("rev"))},
        )
        self.registry.register(
            OperationType.RESTORE_EDIT,
            r"restore\s+(?:the\s+)?version\s+before\s+(?:the\s+)?last\s+(?P<count>\d+|one|two|three|four|five)\s+edits?[\.\!]?",
            lambda m: {
                "steps_back": {
                    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5
                }.get(m.group("count").lower(), int(m.group("count")) if m.group("count").isdigit() else 1)
            },
        )
        self.registry.register(
            OperationType.RESTORE_EDIT,
            r"^(?:reset|start\s+over|restore\s+original|revert\s+all)[\.\!]?$",
            lambda m: {"target_revision": 0},
        )

        # 20. Find where I say X and mute that sentence/phrase
        self.registry.register(
            OperationType.MUTE,
            r"find\s+where\s+(?:i\s+say|someone\s+says)\s+[\"']?(?P<find_phrase>[^\"'\n\.,]+)[\"']?\s+and\s+mute\s+(?:that\s+)?(?:sentence|word|phrase|part)?",
            lambda m: {"phrase": m.group("find_phrase").strip()},
        )

        # 21. Make the ending faster
        self.registry.register(
            OperationType.SPEED_CHANGE,
            r"(?:make\s+(?:the\s+)?(?:ending|end)\s+(?P<spd>[\d\.]+)x?\s+faster|speed\s+up\s+(?:the\s+)?(?:ending|end)\s+(?:by\s+)?(?P<spd2>[\d\.]+)x?)",
            lambda m: {"target": "ending", "speed": float(m.group("spd") or m.group("spd2"))},
        )
        self.registry.register(
            OperationType.SPEED_CHANGE,
            r"(?:change|set|adjust)\s+(?:the\s+)?speed\s+of\s+(?:the\s+)?(?:ending|end|outro|last\s+part)\s+(?:to|at)\s+(?P<speed>[\d\.]+)x?",
            lambda m: {"target": "ending", "speed": float(m.group("speed"))},
        )

        # 22. Vertical Reel / Aspect Ratio / Create Reel
        self.registry.register(
            OperationType.CREATE_REEL,
            r"(?:create|make)\s+(?:(?:this|it)\s+)?(?:a\s+)?(?:(?P<dur>\d+)(?:-|\s*)second\s+)?vertical\s+(?:reel|short|video)(?:\s+from\s+.*)?",
            lambda m: {
                "preset": "vertical_reel",
                "aspect_ratio": "9:16",
                "target_duration": float(m.group("dur")) if m.group("dur") else 30.0,
                "target_duration_s": float(m.group("dur")) if m.group("dur") else 30.0,
            },
        )
        self.registry.register(
            OperationType.SET_ASPECT_RATIO,
            r"(?:set|change|make)\s+(?:(?:this|it)\s+)?(?:aspect\s+ratio\s+to\s+)?(?P<ar>9:16|16:9|1:1|vertical|landscape|square)(?:\s+(?:aspect\s+ratio|format|mode))?",
            lambda m: {"aspect_ratio": m.group("ar")},
        )
        self.registry.register(
            OperationType.VIDEO_TRANSFORM,
            r"(?:rotate|turn)\s+(?:the\s+)?(?:video|clip|footage)?\s*(?:by\s+)?(?P<degrees>90|180|270|quarter[- ]?turn)\s*(?:degrees?)?\s*(?P<direction>clockwise|counterclockwise|anticlockwise|left|right)?",
            lambda m: {
                "rotation_degrees": (
                    90 if m.group("degrees").lower().startswith("quarter") else
                    (360 - int(m.group("degrees")) if (m.group("direction") or "").lower() in {"left", "counterclockwise", "anticlockwise"} else int(m.group("degrees")))
                ) % 360
            },
        )
        self.registry.register(
            OperationType.VIDEO_TRANSFORM,
            r"(?:mirror|flip)\s+(?:the\s+)?(?:video|clip|footage)?\s*(?P<axis>horizontally|horizontal|vertically|vertical|left[- ]to[- ]right|top[- ]to[- ]bottom)?",
            lambda m: {
                "horizontal_flip": (m.group("axis") or "horizontal").lower() in {"horizontally", "horizontal", "left-to-right"},
                "vertical_flip": (m.group("axis") or "horizontal").lower() in {"vertically", "vertical", "top-to-bottom"},
            },
        )

        # 23. Cinematic colour grade
        self.registry.register(
            OperationType.COLOR_GRADE,
            r"(?:reset|clear|remove)\s+(?:(?:the|my)\s+)?colou?r\s+(?:grade|effects?)(?:\s+(?:to\s+)?(?:original|default|normal))?",
            lambda m: {"preset": "original"},
        )
        self.registry.register(
            OperationType.COLOR_GRADE,
            r"(?:(?:apply|add|use|give)\s+)?(?:a\s+)?warm\s+cinematic\s+(?:colou?r\s+)?(?:grade|look|preset)",
            lambda m: {"preset": "warm"},
        )
        self.registry.register(
            OperationType.COLOR_GRADE,
            r"(?:(?:give|apply|add|make|use)\s+)?(?:(?:the|this|my)\s+)?(?:video\s+)?(?:a\s+)?cinematic(?:\s+(?:colou?r\s+)?(?:grade|look|preset|edit|video))?",
            lambda m: {"preset": "cinematic"},
        )
        self.registry.register(
            OperationType.COLOR_GRADE,
            r"(?:(?:apply|change|make|turn|convert|set|use)\s+)?(?:(?:this\s+|the\s+)?(?:video|clip|footage)\s+)?(?:(?:to|into)\s+)?(?:(?:colou?r\s+(?:grade|preset)|preset)\s+)?(?P<preset>sepia|grayscale|gray\s*scale|grey\s*scale|warm|cool|black(?:\s+(?:and|&))?\s*white|b\s*&\s*w|monochrome|monochromatic)(?:\s+(?:colou?r\s+(?:grade|preset)|preset|filter|effect|look))?",
            lambda m: {
                "preset": (
                    "grayscale"
                    if re.sub(r"[\s&-]+", "", m.group("preset").lower())
                    in {"grayscale", "greyscale", "blackwhite", "blackandwhite", "bw", "monochrome", "monochromatic"}
                    else m.group("preset").lower()
                )
            },
        )

        # 24. Clip-to-clip crossfade and dissolve transitions
        self.registry.register(
            OperationType.ADD_TRANSITION,
            r"(?:add|apply)\s+(?:smooth\s+)?transitions?",
            lambda m: {
                "type": "clip_transition",
                "transition_type": "crossfade",
                "duration": 0.75,
            },
        )
        self.registry.register(
            OperationType.ADD_TRANSITION,
            r"(?:add|apply)\s+(?:a\s+)?(?P<kind>cross[- ]?fade|dissolve)(?:\s+transition)?(?:\s+between\s+(?:the\s+)?clips?)?(?:\s+(?:of\s+)?(?P<dur>[\d\.]+)\s*(?:s|seconds?)?)?",
            lambda m: {
                "type": "clip_transition",
                "transition_type": "dissolve" if m.group("kind").lower() == "dissolve" else "crossfade",
                "duration": float(m.group("dur")) if m.group("dur") else 0.75,
            },
        )
        self.registry.register(
            OperationType.ADD_TRANSITION,
            r"(?:add|apply)\s+(?:a\s+)?(?P<dur>[\d\.]+)\s*(?:s|seconds?)?\s+(?P<kind>cross[- ]?fade|dissolve)(?:\s+transition)?",
            lambda m: {
                "type": "clip_transition",
                "transition_type": "dissolve" if m.group("kind").lower() == "dissolve" else "crossfade",
                "duration": float(m.group("dur")),
            },
        )

        # 25. Smooth fade-in and fade-out
        self.registry.register(
            OperationType.ADD_TRANSITION,
            r"(?:add|apply)\s+(?:a\s+)?(?:smooth\s+)?fade[- ]in\s+(?:and\s+)?fade[- ]out(?:\s+(?:of\s+)?(?P<dur>[\d\.]+)s?)?",
            lambda m: {
                "type": "fade_in_out",
                "transition_type": "fade_in_out",
                "duration": float(m.group("dur")) if m.group("dur") else 1.0,
            },
        )

        # 26. Audio ducking
        self.registry.register(
            OperationType.AUDIO_DUCKING,
            r"(?:lower|duck)\s+(?:the\s+)?music\s+when\s+someone\s+speaks|enable\s+audio\s+ducking|duck\s+music",
            lambda m: {"enabled": True, "attenuation_db": 12.0},
        )

        # 26. Professional introduction with animated text
        self.registry.register(
            OperationType.ADD_TEXT_OVERLAY,
            r"(?:create|add)\s+(?:a\s+)?(?:professional\s+)?intro(?:duction)?(?:\s+with\s+animated\s+text)?(?:\s+[\"'](?P<text>[^\"']+)[\"'])?",
            lambda m: {
                "text": m.group("text") or "Welcome",
                "position": "center",
                "source_start": 0.0,
                "source_end": 4.0,
            },
        )

        # 27. Blur background region
        self.registry.register(
            OperationType.BLUR_REGION,
            r"blur\s+(?:the\s+)?(?:selected\s+)?(?:background|region|video)(?:\s+by\s+(?P<radius>\d+))?",
            lambda m: {"blur_radius": float(m.group("radius")) if m.group("radius") else 10.0},
        )

        # 28. Educational video preset
        self.registry.register(
            OperationType.APPLY_PRESET,
            r"make\s+(?:this|it|video)\s+look\s+like\s+an?\s+educational\s+video|educational\s+(?:preset|look|mode)",
            lambda m: {"preset": "educational"},
        )

        # 29. Audio normalization
        self.registry.register(
            OperationType.AUDIO_NORMALIZE,
            r"(?:normalize|level)\s+audio|audio\s+normalization",
            lambda m: {"enabled": True},
        )

        # 31. Reduce steady background noise in source audio.
        self.registry.register(
            OperationType.AUDIO_DENOISE,
            r"(?:reduce|remove|clean(?:\s+up)?|denoise|de-noise)\s+(?:the\s+)?(?:(?:background|wind|audio|noise)\s*(?:audio\s*)?(?:noise)?|background\s+audio\s+noise)(?:\s+from\s+(?:the\s+)?(?:audio|video|clip))?",
            lambda m: {"enabled": True, "reduction_db": 12.0},
        )
        self.registry.register(
            OperationType.AUDIO_DENOISE,
            r"(?:apply|enable)\s+(?:audio\s+)?noise\s+reduction",
            lambda m: {"enabled": True, "reduction_db": 12.0},
        )

        # 30. Tamil / Thanglish NLP rules
        self.registry.register(
            OperationType.CUT_RANGE,
            r"(?:mudhal|aarambathula)\s+(?P<dur>[\d:\.]+s?)\s*(?:seconds|sec|s)?\s*(?:-ai\s+)?(?:cut|remove|delete)\s*(?:pannu|sey)?",
            lambda m: {"start": 0.0, "end": parse_timestamp(m.group("dur")), "time_basis": "source"},
        )
        self.registry.register(
            OperationType.CUT_RANGE,
            r"kadaisi\s+(?P<dur>[\d:\.]+s?)\s*(?:seconds|sec|s)?\s*(?:-ai\s+)?(?:cut|remove)\s*pannu",
            lambda m: {"start": -parse_timestamp(m.group("dur")), "end": 999999.0, "time_basis": "current_timeline"},
        )
        self.registry.register(
            OperationType.REMOVE_SILENCE,
            r"(?:neram\s+athigama\s+irukura\s+)?pauses?(?:\s*-ai)?\s*(?:remove|cut)\s*pannu",
            lambda m: {"threshold_seconds": 1.0},
        )
        self.registry.register(
            OperationType.GENERATE_CAPTIONS,
            r"(?:subtitles?|captions?)\s*(?:add\s*pannu|podu)",
            lambda m: {},
        )
        self.registry.register(
            OperationType.COLOR_GRADE,
            r"cinematic\s*(?:colour|color)?\s*(?:grade|look)\s*(?:podu|kudu)",
            lambda m: {"preset": "cinematic"},
        )
        self.registry.register(
            OperationType.UNDO,
            r"undo\s*pannu",
            lambda m: {},
        )
        self.registry.register(
            OperationType.REDO,
            r"redo\s*pannu",
            lambda m: {},
        )
        self.registry.register(
            OperationType.SET_ASPECT_RATIO,
            r"(?:video|clip)(?:-va)?\s+(?P<ar>9:16|16:9|1:1)\s*(?:la|format-la)?\s*(?:maathu|maathu|change\s+pannu)",
            lambda m: {"aspect_ratio": m.group("ar")},
        )
        self.registry.register(
            OperationType.AUDIO_NORMALIZE,
            r"(?:audio|sound)(?:-va)?\s+(?:normalize|level)(?:\s+pannu|\s+sey)",
            lambda m: {"enabled": True},
        )

        # 32. Additional Part 2 Natural Language & Professional Operations
        # Brighter and more colorful
        self.registry.register(
            OperationType.COLOR_GRADE,
            r"(?:make\s+(?:this|the|my)?\s*(?:video|clip)?\s*)?(?:brighter\s+and\s+more\s+colou?rful|boost\s+colou?rs|more\s+vibrant)",
            lambda m: {"brightness": 0.08, "saturation": 1.25, "contrast": 1.1},
        )
        # Vintage film look / Sepia
        self.registry.register(
            OperationType.COLOR_GRADE,
            r"(?:apply|give|use)\s+(?:a\s+)?(?:vintage|retro|old[- ]school)(?:\s+film)?(?:\s+look|\s+preset|\s+grade)",
            lambda m: {"preset": "sepia", "vignette": True},
        )
        # Vignette
        self.registry.register(
            OperationType.COLOR_GRADE,
            r"(?:apply|add|enable)\s+(?:a\s+)?vignette(?:\s+effect)?",
            lambda m: {"vignette": True},
        )
        # Dialogue clarity
        self.registry.register(
            OperationType.AUDIO_DENOISE,
            r"make\s+(?:the\s+)?dialogue\s+(?:clearer|cleaner|crisp)|clear(?:er)?\s+dialogue",
            lambda m: {"enabled": True, "reduction_db": 12.0},
        )
        # Wipe transition
        self.registry.register(
            OperationType.ADD_TRANSITION,
            r"(?:add|apply)\s+(?:a\s+)?wipe(?:\s+transition)?(?:\s+between\s+(?:the\s+)?clips?)?(?:\s+(?:of\s+)?(?P<dur>[\d\.]+)\s*(?:s|seconds?)?)?",
            lambda m: {
                "type": "clip_transition",
                "transition_type": "wipe",
                "duration": float(m.group("dur")) if m.group("dur") else 0.75,
            },
        )
        # Make previous transition shorter
        self.registry.register(
            OperationType.ADD_TRANSITION,
            r"make\s+(?:the\s+)?(?:previous\s+)?transition\s+(?:shorter|faster)(?:\s+to\s+(?P<dur>[\d\.]+)s?)?",
            lambda m: {
                "type": "clip_transition",
                "transition_type": "fade",
                "duration": float(m.group("dur")) if m.group("dur") else 0.5,
            },
        )
        # Smooth transitions generic
        self.registry.register(
            OperationType.ADD_TRANSITION,
            r"(?:add|apply)\s+smooth\s+transitions?(?:\s+between\s+(?:the\s+)?clips?)?",
            lambda m: {"type": "clip_transition", "transition_type": "fade", "duration": 1.0},
        )
        # Convert landscape to vertical short
        self.registry.register(
            OperationType.SET_ASPECT_RATIO,
            r"convert\s+(?:this\s+)?(?:landscape\s+video\s+to\s+(?:a\s+)?)?vertical\s+(?:short|reel|format)|convert\s+to\s+vertical\s*(?:short|reel)?",
            lambda m: {"aspect_ratio": "9:16"},
        )
        # Portrait 4:5
        self.registry.register(
            OperationType.SET_ASPECT_RATIO,
            r"(?:convert|set|change)\s+(?:aspect\s+ratio\s+to\s+)?(?:4:5|portrait)(?:\s+aspect\s+ratio|\s+format)?",
            lambda m: {"aspect_ratio": "4:5"},
        )
        # Split clip at timestamp
        self.registry.register(
            OperationType.SPLIT_CLIP,
            r"(?:split|cut)\s+(?:the\s+)?(?:clip|video|segment)\s+(?:in\s+two\s+|in\s+half\s+)?(?:at\s+)?(?P<time>[\d:\.]+s?)",
            lambda m: {"split_time": parse_timestamp(m.group("time")), "time_basis": "current_timeline"},
        )
        # Duplicate clip
        self.registry.register(
            OperationType.DUPLICATE_CLIP,
            r"duplicate\s+(?:the\s+|this\s+)?(?:(?P<ordinal>first|second|third)\s+)?(?:clip|segment)(?:\s+(?P<id>seg_[a-zA-Z0-9_]+))?",
            lambda m: {
                **({"segment_id": m.group("id")} if m.group("id") else {}),
                **({"index": {"first": 0, "second": 1, "third": 2}[m.group("ordinal").lower()]} if m.group("ordinal") else {}),
            },
        )
        # Logo and watermark
        self.registry.register(
            OperationType.ADD_TEXT_OVERLAY,
            r"(?:add|put|insert)\s+(?:a\s+)?(?:logo\s+and\s+)?watermark(?:\s+[\"'](?P<txt>[^\"']+)[\"'])?",
            lambda m: {"text": m.group("txt") or "IncuBrix EditStudio", "position": "watermark"},
        )
        # Credits at end
        self.registry.register(
            OperationType.ADD_TEXT_OVERLAY,
            r"(?:add|put|insert)\s+credits(?:\s+at\s+the\s+end)?(?:\s+[\"'](?P<txt>[^\"']+)[\"'])?",
            lambda m: {"text": m.group("txt") or "Edited with IncuBrix EditStudio", "position": "credits"},
        )
        # Lower third
        self.registry.register(
            OperationType.ADD_TEXT_OVERLAY,
            r"(?:add|insert)\s+(?:a\s+)?lower\s+third\s+[\"'](?P<txt>[^\"']+)[\"']",
            lambda m: {"text": m.group("txt").strip(), "position": "lower_third"},
        )
        # Advertisement preset
        self.registry.register(
            OperationType.APPLY_PRESET,
            r"(?:create|make)\s+(?:a\s+)?(?:professional\s+)?advertisement(?:\s+look)?",
            lambda m: {"preset": "educational"},
        )
        # Montage from all uploaded clips
        self.registry.register(
            OperationType.APPLY_PRESET,
            r"make\s+(?:a\s+)?fast[- ]paced\s+montage(?:\s+from\s+all\s+uploaded\s+clips)?",
            lambda m: {"preset": "vertical_reel"},
        )
        # Keep original audio but change video colors
        self.registry.register(
            OperationType.COLOR_GRADE,
            r"keep\s+(?:the\s+)?original\s+audio\s+(?:but|and)\s+change\s+(?:the\s+)?(?:video\s+)?colou?rs?",
            lambda m: {"preset": "cinematic"},
        )
        # Keep everything unchanged except color grading
        self.registry.register(
            OperationType.COLOR_GRADE,
            r"keep\s+everything\s+unchanged\s+except\s+(?:the\s+)?colou?r\s+grading",
            lambda m: {"preset": "cinematic"},
        )
        # Remove subtitles and generate new ones
        self.registry.register(
            OperationType.GENERATE_CAPTIONS,
            r"remove\s+subtitles\s+and\s+generate\s+new\s+ones",
            lambda m: {},
        )

    @staticmethod
    def _parse_natural_time_instruction(text: str, timeline: Timeline) -> Optional[OperationProposal]:
        """Parse unit/spoken-time edit ranges before numeric regex rules."""
        raw = text.strip()
        source_time = bool(re.search(r"\b(?:original|source)\b", raw, re.IGNORECASE))
        basis = "source" if source_time else "current_timeline"
        duration_s = timeline.source_metadata.duration if source_time else timeline.total_output_duration
        duration_tick = int(round(duration_s * TICKS_PER_SECOND))
        suffix = re.search(r"\s+(?:in\s+the\s+)?(?:original\s+)?(?:source|timeline|edited\s+video)$", raw, re.IGNORECASE)
        if suffix:
            raw = raw[:suffix.start()].strip()

        speed_match = re.fullmatch(
            r"(?P<verb>speed\s+up|slow\s+down)\s+(?:from\s+)?(?P<start>.+?)\s+(?:to|-)\s+(?P<end>.+?)\s+(?:by|to)\s+(?P<speed>\d+(?:\.\d+)?)x?",
            raw, re.IGNORECASE,
        )
        if speed_match:
            start_tick = duration_ticks(speed_match.group("start"))
            end_tick = duration_ticks(speed_match.group("end"))
            if start_tick >= end_tick or end_tick > duration_tick:
                raise ValueError("Speed range is outside the selected timeline")
            return OperationProposal(
                operation_type=OperationType.SPEED_CHANGE,
                parameters={
                    "start": start_tick / TICKS_PER_SECOND,
                    "end": end_tick / TICKS_PER_SECOND,
                    "speed": float(speed_match.group("speed")),
                    "time_basis": basis,
                },
                provenance="deterministic_time_parser",
            )

        action_match = re.match(
            r"^(?P<verb>cut|trim|delete|remove|keep|mute|bleep)\s+(?P<body>.+)$",
            raw, re.IGNORECASE,
        )
        if not action_match:
            return None
        verb = action_match.group("verb").lower()
        body = re.sub(r"^(?:from|between)\s+", "", action_match.group("body"), flags=re.IGNORECASE)
        range_match = re.fullmatch(r"(?P<start>.+?)\s+(?:to|and)\s+(?P<end>.+)", body, re.IGNORECASE)
        if range_match:
            start_tick = duration_ticks(range_match.group("start"))
            end_tick = duration_ticks(range_match.group("end"))
            if start_tick >= end_tick:
                raise ValueError("Time range start must be before its end")
            if end_tick > duration_tick:
                raise ValueError("Time range exceeds the selected timeline duration")
        else:
            relative = re.fullmatch(r"(?:the\s+)?(?:first|last)\s+.+", body, re.IGNORECASE)
            if not relative:
                return None
            parsed = parse_time_expression(body, duration_tick)
            start_tick, end_tick = parsed.start_tick, parsed.end_tick

        operation_type = {
            "cut": OperationType.CUT_RANGE,
            "trim": OperationType.CUT_RANGE,
            "delete": OperationType.CUT_RANGE,
            "remove": OperationType.CUT_RANGE,
            "keep": OperationType.KEEP_RANGE,
            "mute": OperationType.MUTE,
            "bleep": OperationType.BLEEP,
        }[verb]
        params: Dict[str, Any] = {
            "start": start_tick / TICKS_PER_SECOND,
            "end": end_tick / TICKS_PER_SECOND,
            "time_basis": basis,
        }
        if operation_type == OperationType.BLEEP:
            params["frequency_hz"] = 1000.0
        return OperationProposal(
            operation_type=operation_type,
            parameters=params,
            provenance="deterministic_time_parser",
        )


    def parse_instruction(self, text: str, timeline: Timeline) -> OperationProposal:
        """
        Parse instruction string against rules and disambiguate against timeline transcript.
        Raises:
            ClarificationNeeded: if instruction is ambiguous across multiple transcript matches.
            ValueError: if instruction cannot be parsed or targets invalid ranges.
        """
        raw_text = text.strip()
        if not raw_text:
            raise ValueError("Empty instruction provided")

        # Disallow vague instructions
        vague_patterns = [r"^make it (better|good|cool|clean)$", r"^fix (it|video)$", r"^edit (video|it)$", r"^cut the bad part$"]
        for vp in vague_patterns:
            if re.search(vp, raw_text, re.IGNORECASE):
                raise ValueError("Vague instruction without specified time range, target words, or operation parameters.")

        clean_text = raw_text.rstrip(".!?;")
        proposal = None
        tail_match = re.search(
            r"\bremove\s+everything\s+after\s+(?:i\s+say\s+|the\s+word\s+|the\s+phrase\s+)?[\"']?(?P<phrase>[\w'-]+(?:\s+[\w'-]+)*)[\"']?$",
            clean_text,
            re.IGNORECASE,
        )
        if tail_match:
            proposal = OperationProposal(
                operation_type=OperationType.CUT_RANGE,
                parameters={
                    "phrase": tail_match.group("phrase").strip(),
                    "cut_after_phrase": True,
                    "time_basis": "source",
                },
            )
        if re.search(r"\b(?:hours?|hrs?|minutes?|mins?|seconds?|secs?|a\s+minute|one\s+minute|\d+h(?:\d+m)?)\b", raw_text, re.IGNORECASE):
            proposal = proposal or self._parse_natural_time_instruction(raw_text, timeline)
        proposal = proposal or self.registry.parse(clean_text) or self.registry.parse(raw_text)
        if not proposal:
            raise ValueError(f"Unrecognized instruction: '{raw_text}'. Please specify an action such as cut, keep, remove phrase, speed, mute, bleep, caption, or undo.")

        explicit_source_time = bool(re.search(r"\b(?:original|source)\b", raw_text, re.IGNORECASE))

        # Handle dynamic range adjustments for cuts and keeps
        if proposal.operation_type in (OperationType.CUT_RANGE, OperationType.CUT_TIME):
            if proposal.parameters.get("start", 0) < 0:
                dur = abs(proposal.parameters["start"])
                total_dur = timeline.source_metadata.duration if explicit_source_time else timeline.total_output_duration
                proposal.parameters["start"] = max(0.0, total_dur - dur)
                proposal.parameters["end"] = total_dur
        speed_target = proposal.parameters.get("target", "") if proposal.operation_type == OperationType.SPEED_CHANGE else ""
        if proposal.operation_type == OperationType.SPEED_CHANGE and (speed_target == "ending" or str(speed_target).startswith("ending_")):
            total_dur = timeline.source_metadata.duration if explicit_source_time else timeline.total_output_duration
            requested_duration = proposal.parameters.pop("ending_duration", None)
            if requested_duration is None:
                try:
                    requested_duration = float(str(speed_target).split("_", 1)[1])
                except (IndexError, ValueError):
                    requested_duration = None
            dur_ending = min(total_dur, requested_duration) if requested_duration is not None else min(15.0, max(2.0, total_dur * 0.25))
            proposal.parameters["start"] = max(0.0, total_dur - dur_ending)
            proposal.parameters["end"] = total_dur

        if proposal.operation_type in (OperationType.RESTORE_EDIT, OperationType.RESTORE_REVISION) and "steps_back" in proposal.parameters:
            target_rev = max(0, timeline.revision - proposal.parameters["steps_back"])
            proposal.parameters["target_revision"] = target_rev

        if "start" in proposal.parameters and "start_time" not in proposal.parameters:
            proposal.parameters["start_time"] = proposal.parameters["start"]
        if "end" in proposal.parameters and "end_time" not in proposal.parameters:
            proposal.parameters["end_time"] = proposal.parameters["end"]
        if "threshold_seconds" in proposal.parameters and "min_silence_s" not in proposal.parameters:
            proposal.parameters["min_silence_s"] = proposal.parameters["threshold_seconds"]

        timed_range_ops = {
            OperationType.CUT_RANGE, OperationType.KEEP_RANGE, OperationType.SPEED_CHANGE,
            OperationType.MUTE, OperationType.BLEEP,
        }
        if proposal.operation_type in timed_range_ops:
            if "start" in proposal.parameters and "end" in proposal.parameters and not proposal.parameters.get("word_ids"):
                proposal.parameters["time_basis"] = "source" if explicit_source_time else "current_timeline"
                upper_bound = (
                    timeline.source_metadata.duration
                    if proposal.parameters["time_basis"] == "source"
                    else timeline.total_output_duration
                )
                if proposal.parameters["end"] > upper_bound:
                    proposal.parameters["end"] = upper_bound
                    proposal.parameters["end_time"] = upper_bound

        # Check transcript anchoring and ambiguities
        op_type = proposal.operation_type
        params = proposal.parameters


        if op_type in (OperationType.REMOVE_PHRASE, OperationType.MUTE, OperationType.BLEEP, OperationType.ADD_CAPTION, OperationType.CUT_RANGE):
            phrase = params.get("phrase") or params.get("anchor_phrase")
            if phrase:
                # Check occurrence qualifiers: "first occurrence", "second occurrence", "last occurrence", or speaker
                occurrence_idx = None
                if re.search(r"\bfirst\b", raw_text, re.IGNORECASE):
                    occurrence_idx = 0
                elif re.search(r"\bsecond\b", raw_text, re.IGNORECASE):
                    occurrence_idx = 1
                elif re.search(r"\blast\b", raw_text, re.IGNORECASE):
                    occurrence_idx = -1

                speaker = None
                spk_match = re.search(r"spoken by\s+(?:speaker\s+)?(?P<spk>[A-Za-z0-9_]+)", raw_text, re.IGNORECASE)
                if spk_match:
                    spk_val = spk_match.group("spk").strip()
                    # Match against speakers in transcript
                    for w in timeline.transcript.words:
                        if w.speaker and (spk_val.lower() == w.speaker.lower() or spk_val.lower() in w.speaker.lower() or f"speaker {spk_val.lower()}" == w.speaker.lower()):
                            speaker = w.speaker
                            break
                    if not speaker:
                        speaker = spk_val

                occurrences = timeline.transcript.find_phrase_occurrences(phrase, speaker=speaker)
                semantic_terms = {
                    "pricing": {"pricing", "price", "prices", "cost", "costs", "fee", "fees", "charge", "charges"},
                    "cost": {"pricing", "price", "prices", "cost", "costs", "fee", "fees", "charge", "charges"},
                }
                if not occurrences and params.get("semantic_search"):
                    query_tokens = [normalize_text(token) for token in phrase.split() if normalize_text(token)]
                    if len(query_tokens) == 1:
                        terms = semantic_terms.get(query_tokens[0], {query_tokens[0]})
                        occurrences = [
                            [word] for word in timeline.transcript.words
                            if (speaker is None or word.speaker == speaker)
                            and normalize_text(word.text) in terms
                        ]

                if not occurrences:
                    if not timeline.transcript.words:
                        raise ValueError(f"Cannot target phrase '{phrase}': No transcript words loaded yet. Please click 'Auto-Transcribe' or 'Load Sample' in the panel.")
                    raise ValueError(f"Phrase '{phrase}' not found in transcript" + (f" for speaker '{speaker}'" if speaker else ""))

                if len(occurrences) == 1:
                    target_words = occurrences[0]
                    self._inject_words_into_proposal(proposal, target_words)
                    if params.get("cut_after_phrase"):
                        params["end"] = timeline.source_metadata.duration
                        params["end_time"] = timeline.source_metadata.duration
                elif occurrence_idx is not None:
                    target_words = occurrences[occurrence_idx]
                    self._inject_words_into_proposal(proposal, target_words)
                    if params.get("cut_after_phrase"):
                        params["end"] = timeline.source_metadata.duration
                        params["end_time"] = timeline.source_metadata.duration
                else:
                    # Ambiguous! Must ask clarification
                    options: List[ClarificationOption] = []
                    for idx, occ in enumerate(occurrences):
                        start_s = occ[0].start
                        end_s = occ[-1].end
                        spk = occ[0].speaker or "Unknown speaker"
                        text_snippet = " ".join(w.text for w in occ)
                        opt_id = f"opt_{idx + 1}"
                        opt_label = f"Occurrence {idx + 1}: '{text_snippet}' at {start_s:.2f}s - {end_s:.2f}s ({spk})"
                        copy_params = dict(params)
                        target_start = occ[-1].end if params.get("cut_after_phrase") else start_s
                        target_end = timeline.source_metadata.duration if params.get("cut_after_phrase") else end_s
                        copy_params.update({"start": target_start, "end": target_end})
                        target_data = {
                            "operation_type": op_type.value,
                            "parameters": copy_params,
                            "word_ids": [w.id for w in occ],
                            "start": target_start,
                            "end": target_end,
                        }
                        options.append(ClarificationOption(id=opt_id, label=opt_label, detail=f"{spk} at {start_s:.2f}s - {end_s:.2f}s", target_data=target_data))

                    question = f"The phrase '{phrase}' appears {len(occurrences)} times in the transcript. Which occurrence would you like to target?"
                    raise ClarificationNeeded(question, options)

        return proposal

    def _inject_words_into_proposal(self, proposal: OperationProposal, words: List[TranscriptWord]) -> None:
        if proposal.operation_type == OperationType.REMOVE_PHRASE:
            proposal.parameters["target_words"] = words
            proposal.parameters["word_ids"] = [w.id for w in words]
            proposal.parameters["start"] = min(w.start for w in words)
            proposal.parameters["end"] = max(w.end for w in words)
            proposal.parameters["start_time"] = proposal.parameters["start"]
            proposal.parameters["end_time"] = proposal.parameters["end"]
        elif proposal.operation_type in (OperationType.MUTE, OperationType.MUTE_TIME, OperationType.BLEEP):
            proposal.parameters["word_ids"] = [w.id for w in words]
            proposal.parameters["start"] = min(w.start for w in words)
            proposal.parameters["end"] = max(w.end for w in words)
            proposal.parameters["start_time"] = proposal.parameters["start"]
            proposal.parameters["end_time"] = proposal.parameters["end"]
        elif proposal.operation_type == OperationType.ADD_CAPTION:
            proposal.parameters["anchor_word_ids"] = [w.id for w in words]
        elif proposal.operation_type == OperationType.CUT_RANGE and proposal.parameters.get("cut_after_phrase"):
            proposal.parameters["start"] = words[-1].end
            proposal.parameters["end_time"] = words[-1].end
            proposal.parameters["word_ids"] = [w.id for w in words]
