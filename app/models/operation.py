from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class InstructionStatus(str, Enum):
    APPLIED = "applied"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"


class OperationType(str, Enum):
    CUT_RANGE = "cut_range"
    CUT_TIME = "cut_range"
    KEEP_RANGE = "keep_range"
    REMOVE_PHRASE = "remove_phrase"
    REORDER_SECTIONS = "reorder_sections"
    SPEED_CHANGE = "speed_change"
    MUTE = "mute"
    MUTE_TIME = "mute"
    BLEEP = "bleep"
    ADD_CAPTION = "add_caption"
    ADD_TEXT_OVERLAY = "add_text_overlay"
    GENERATE_CAPTIONS = "generate_captions"
    REMOVE_FILLER_WORDS = "remove_filler_words"
    REMOVE_SILENCE = "remove_silence"
    ADD_BACKGROUND_MUSIC = "add_background_music"
    COLOR_GRADE = "color_grade"
    SET_CAPTION_STYLE = "set_caption_style"
    SET_CAPTION_MODE = "set_caption_mode"
    ADD_TRANSITION = "add_transition"
    SET_ASPECT_RATIO = "set_aspect_ratio"
    CREATE_REEL = "create_reel"
    BLUR_REGION = "blur_region"
    APPLY_PRESET = "apply_preset"
    AUDIO_NORMALIZE = "audio_normalize"
    AUDIO_DUCKING = "audio_ducking"
    AUDIO_DENOISE = "audio_denoise"
    VIDEO_TRANSFORM = "video_transform"
    SPLIT_CLIP = "split_clip"
    DUPLICATE_CLIP = "duplicate_clip"
    UNDO = "undo"
    REDO = "redo"
    RESTORE_EDIT = "restore_edit"
    RESTORE_REVISION = "restore_edit"



class ClarificationOption(BaseModel):
    id: str = Field(..., description="Stable identifier for choice, e.g. opt_1")
    label: str = Field(..., description="Human readable summary of this choice")
    detail: Optional[str] = Field(default=None, description="Detailed context, timestamp, speaker")
    target_data: Dict[str, Any] = Field(default_factory=dict, description="Pre-computed payload to execute if selected")


class OperationProposal(BaseModel):
    operation_type: OperationType
    parameters: Dict[str, Any]
    provenance: str = "nlp_parser"
    confidence: float = 1.0


from datetime import datetime, timezone

class CommittedOperation(BaseModel):
    operation_id: str
    operation_type: OperationType
    parameters: Dict[str, Any]
    previous_revision: int
    resulting_revision: int
    status: str = "committed"
    state: str = Field(default="active", pattern="^(active|undone|disabled)$")
    provenance: str = "engine"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class InstructionResult(BaseModel):
    request_id: str
    status: InstructionStatus
    message: str
    operations: List[CommittedOperation] = Field(default_factory=list)
    before_summary: Optional[Dict[str, Any]] = None
    after_summary: Optional[Dict[str, Any]] = None
    clarification_question: Optional[str] = None
    options: List[ClarificationOption] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    timeline_hash: Optional[str] = None
    timeline_revision: Optional[int] = None
    duration_s: Optional[float] = None
    time_policy: Optional[str] = None
    operation_id: Optional[str] = None
    error_code: Optional[str] = None
