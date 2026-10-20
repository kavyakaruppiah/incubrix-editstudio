from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RenderVerification(BaseModel):
    is_readable: bool = False
    expected_duration_s: float
    actual_duration_s: float
    duration_difference_s: float
    duration_within_tolerance: bool
    video_stream_present: bool
    audio_stream_present: bool
    audio_video_sync_skew_s: Optional[float] = None
    original_file_hash_verified: bool = True
    original_media_hash: str
    rendered_file_hash: str
    width: Optional[int] = None
    height: Optional[int] = None
    frame_rate: Optional[float] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class RenderManifest(BaseModel):
    render_id: str
    media_id: str
    timeline_revision: int
    timeline_hash: str
    status: JobStatus
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    output_filename: str
    output_path: str
    output_url: str
    file_size_bytes: int = 0
    ffmpeg_command: List[str] = Field(default_factory=list)
    verification: Optional[RenderVerification] = None
    error_message: Optional[str] = None
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)
