from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from app.models.operation import ClarificationOption, CommittedOperation, InstructionStatus
from app.models.render import JobStatus, RenderManifest
from app.models.timeline import Timeline
from app.models.transcript import Transcript


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


class ReadinessResponse(BaseModel):
    status: str
    ffmpeg_available: bool
    ffprobe_available: bool
    storage_writable: bool
    details: Dict[str, Any]


class InstructionRequest(BaseModel):
    instruction: str = Field(..., min_length=1, description="Natural language editing instruction")


class ClarificationAnswerRequest(BaseModel):
    session_id: str = Field(..., description="Clarification session ID")
    selected_option_id: str = Field(..., description="Selected option ID or index (e.g. opt_1)")


class RestoreRequest(BaseModel):
    target_operation_id: Optional[str] = None
    target_revision: Optional[int] = None


class RenderJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class RenderOptions(BaseModel):
    """Safe, per-render encoder settings; output path and codec remain server controlled."""
    quality: int = Field(default=20, ge=16, le=30, description="H.264 CRF quality; lower means higher quality")
    preset: Literal["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"] = "veryfast"
    frame_rate: Literal[24, 25, 30, 50, 60] = 30


class SessionRunRequest(BaseModel):
    session_data: Dict[str, Any]


class ApiErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: Optional[Any] = None


class ApiErrorResponse(BaseModel):
    error: ApiErrorDetail


class EditWordRequest(BaseModel):
    word_id: str
    new_text: Optional[str] = None
    new_start: Optional[float] = None
    new_end: Optional[float] = None
    new_speaker: Optional[str] = None

