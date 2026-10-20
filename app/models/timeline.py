from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
from app.models.media import MediaMetadata
from app.models.operation import CommittedOperation
from app.models.transcript import Transcript


class TimelineSegment(BaseModel):
    segment_id: str
    source_start: float = Field(..., ge=0.0)
    source_end: float = Field(..., ge=0.0)
    speed: float = Field(default=1.0, gt=0.0)
    audio_enabled: bool = True
    video_enabled: bool = True
    label: Optional[str] = None
    transition_in: str = "cut"
    transition_duration: float = Field(default=0.0, ge=0.0, le=2.0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "TimelineSegment":
        if self.source_start >= self.source_end:
            raise ValueError(f"Segment {self.segment_id} source_start ({self.source_start}) must be strictly less than source_end ({self.source_end})")
        return self

    @property
    def source_duration(self) -> float:
        return self.source_end - self.source_start

    @property
    def output_duration(self) -> float:
        return (self.source_end - self.source_start) / self.speed


class CaptionStyle(BaseModel):
    font_name: str = "Arial"
    font_size: int = 24
    bold: bool = True
    italic: bool = False
    primary_color: str = "&H00FFFFFF"  # White in ASS (&HAABBGGRR)
    outline_color: str = "&H00000000"  # Black outline in ASS
    outline_width: int = 2
    shadow_color: str = "&H80000000"
    shadow_offset: int = 1
    back_color: str = "&H80000000"     # Background box color
    border_style: int = 1              # 1=Outline+Shadow, 3=Opaque background box
    position: str = "bottom"           # bottom, top, center
    alignment: int = 2                 # 2=bottom-center, 8=top-center, 5=center
    margin_v: int = 40
    karaoke_color: str = "&H0000FFFF"  # Yellow in ASS
    mode: str = "sentence"             # sentence, word_by_word, karaoke, speaker_labelled


class VideoEffectsContainer(BaseModel):
    color_grade: Optional[str] = None  # cinematic, grayscale, sepia, warm, cool
    brightness: float = 0.0            # -1.0 to 1.0
    contrast: float = 1.0              # 0.1 to 3.0
    saturation: float = 1.0            # 0.0 to 3.0
    gamma: float = 1.0                 # 0.1 to 3.0
    blur: Optional[float] = None       # Gaussian blur radius
    sharpen: Optional[float] = None
    vignette: bool = False             # Vignette effect
    fade_in_duration: float = 0.0      # Fade in duration in seconds
    fade_out_duration: float = 0.0     # Fade out duration in seconds
    aspect_ratio: str = "original"     # 16:9, 9:16, 1:1, original
    rotation_degrees: int = Field(default=0, ge=0, le=270)
    horizontal_flip: bool = False
    vertical_flip: bool = False
    audio_ducking: bool = True
    audio_normalize: bool = False
    transitions: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_transitions(self) -> "VideoEffectsContainer":
        if "fade_in_out" in self.transitions or "fade" in self.transitions:
            if self.fade_in_duration <= 0.0:
                self.fade_in_duration = 1.0
            if self.fade_out_duration <= 0.0:
                self.fade_out_duration = 1.0
        return self


class TimelineCaption(BaseModel):
    caption_id: str
    text: str
    anchor_word_ids: List[str] = Field(default_factory=list)
    anchor_phrase: Optional[str] = None
    style: CaptionStyle = Field(default_factory=CaptionStyle)


class TimelineTextOverlay(BaseModel):
    overlay_id: str
    text: str
    anchor_word_ids: Optional[List[str]] = None
    source_start: Optional[float] = None
    source_end: Optional[float] = None
    output_start: Optional[float] = None
    output_end: Optional[float] = None
    position: str = "bottom"
    style: Dict[str, Any] = Field(default_factory=dict)


class MuteEffect(BaseModel):
    mute_id: str
    source_start: float = Field(..., ge=0.0)
    source_end: float = Field(..., ge=0.0)
    word_ids: List[str] = Field(default_factory=list)


class BleepEffect(BaseModel):
    bleep_id: str
    source_start: float = Field(..., ge=0.0)
    source_end: float = Field(..., ge=0.0)
    frequency_hz: float = Field(default=1000.0, ge=100.0, le=5000.0)
    word_ids: List[str] = Field(default_factory=list)


class AudioEffectsContainer(BaseModel):
    mutes: List[MuteEffect] = Field(default_factory=list)
    bleeps: List[BleepEffect] = Field(default_factory=list)
    noise_reduction_db: float = Field(default=0.0, ge=0.0, le=30.0)


class BackgroundMusic(BaseModel):
    track_id: str = "default_bgm"
    track_path: Optional[str] = None
    volume: float = Field(default=0.2, ge=0.0, le=2.0)
    ducking_enabled: bool = True
    ducking_attenuation_db: float = Field(default=12.0)
    speech_threshold: float = Field(default=0.05)


class TimePolicy(BaseModel):
    source_time_definition: str = (
        "Time in seconds relative to original media start (0.0s to duration). "
        "Source intervals are immutable and refer directly to the uploaded media."
    )
    timeline_time_definition: str = (
        "Derived cumulative time in seconds across ordered retained segments. "
        "For each segment i, output_duration = (source_end - source_start) / speed. "
        "output_start_i = sum(output_duration_0..i-1)."
    )
    speed_derivation_rule: str = (
        "Duration_output = (source_end - source_start) / speed. "
        "Speed > 1 accelerates playback (shorter duration); speed < 1 decelerates (longer duration)."
    )


class Timeline(BaseModel):
    schema_version: str = "1.0.0"
    media_id: str
    original_media_hash: str
    source_metadata: MediaMetadata
    transcript: Transcript = Field(default_factory=Transcript)
    segments: List[TimelineSegment] = Field(default_factory=list)
    captions: List[TimelineCaption] = Field(default_factory=list)
    global_caption_style: CaptionStyle = Field(default_factory=CaptionStyle)
    caption_mode: str = "sentence"
    text_overlays: List[TimelineTextOverlay] = Field(default_factory=list)
    audio_effects: AudioEffectsContainer = Field(default_factory=AudioEffectsContainer)
    video_effects: VideoEffectsContainer = Field(default_factory=VideoEffectsContainer)
    effects: Optional[VideoEffectsContainer] = None
    aspect_ratio: Optional[str] = None
    background_music: Optional[BackgroundMusic] = None
    revision: int = 0
    history: List[CommittedOperation] = Field(default_factory=list)
    time_policy: TimePolicy = Field(default_factory=TimePolicy)
    warnings: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_aliases(self) -> "Timeline":
        if self.effects is not None:
            self.video_effects = self.effects
        if self.aspect_ratio is not None and self.aspect_ratio != "original":
            self.video_effects.aspect_ratio = self.aspect_ratio
        for index, segment in enumerate(self.segments):
            if segment.transition_in not in {"cut", "crossfade", "dissolve", "wipe"}:
                raise ValueError(f"Unsupported transition '{segment.transition_in}' on segment {segment.segment_id}")
            if index == 0:
                segment.transition_in = "cut"
                segment.transition_duration = 0.0
            elif segment.transition_in == "cut":
                segment.transition_duration = 0.0
            elif segment.transition_duration > 0:
                previous_duration = self.segments[index - 1].output_duration
                segment.transition_duration = min(
                    segment.transition_duration,
                    previous_duration,
                    segment.output_duration,
                )
        return self


    @property
    def total_output_duration(self) -> float:
        return sum(seg.output_duration for seg in self.segments) - sum(
            seg.transition_duration for seg in self.segments[1:]
        )

    def summary(self) -> Dict[str, Any]:
        return {
            "revision": self.revision,
            "segment_count": len(self.segments),
            "output_duration_s": round(self.total_output_duration, 4),
            "caption_count": len(self.captions),
            "overlay_count": len(self.text_overlays),
            "mute_count": len(self.audio_effects.mutes),
            "bleep_count": len(self.audio_effects.bleeps),
            "has_bgm": self.background_music is not None,
            "history_length": len(self.history),
        }
