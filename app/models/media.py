from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class MediaMetadata(BaseModel):
    duration: float = Field(..., ge=0, description="Duration in seconds")
    width: int = Field(..., gt=0, description="Video width in pixels")
    height: int = Field(..., gt=0, description="Video height in pixels")
    frame_rate: float = Field(default=30.0, ge=0, description="Nominal or average frame rate")
    video_codec: str = Field(..., description="Video stream codec name")
    audio_present: bool = Field(default=False, description="Whether an audio stream is detected")
    sample_rate: Optional[int] = Field(default=None, description="Audio sample rate in Hz")
    channels: Optional[int] = Field(default=None, description="Number of audio channels")
    is_vfr: bool = Field(default=False, description="Whether media has variable frame rate")
    file_size: int = Field(..., ge=0, description="File size in bytes")


class MediaManifest(BaseModel):
    media_id: str
    original_filename: str
    storage_filename: str
    storage_path: str
    file_size: int
    sha256_hash: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: MediaMetadata
