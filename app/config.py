import os
import shutil
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "development"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Storage
    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_DIR: str = "./data/storage"
    RENDER_OUTPUT_DIR: str = "./data/renders"
    TEMP_DIR: str = "./data/temp"
    MAX_UPLOAD_SIZE_MB: int = 500

    # Optional S3 / MinIO
    S3_ENDPOINT_URL: Optional[str] = None
    S3_ACCESS_KEY_ID: Optional[str] = None
    S3_SECRET_ACCESS_KEY: Optional[str] = None
    S3_BUCKET_NAME: str = "video-editor-media"
    S3_REGION: str = "us-east-1"

    # SQLite persistence
    DATABASE_URL: str = "sqlite:///./data/app.db"

    # FFmpeg & FFprobe
    FFMPEG_BINARY: Optional[str] = None
    FFPROBE_BINARY: Optional[str] = None

    # Transcription
    TRANSCRIPTION_BACKEND: str = "auto"
    WHISPER_MODEL_SIZE: str = "tiny"
    WHISPER_DEVICE: str = "cpu"
    GOOGLE_SPEECH_FALLBACK_ENABLED: bool = False

    # Local Ollama is preferred; auto mode falls back to deterministic rules offline.
    INSTRUCTION_PROVIDER: str = "auto"
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = ""
    OLLAMA_FALLBACK_MODELS: str = ""
    OLLAMA_TIMEOUT_SECONDS: float = 20.0
    # Optional Cloud AI (Gemini)
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TIMEOUT_SECONDS: float = 30.0
    ELEVENLABS_API_KEY: Optional[str] = None
    ELEVENLABS_STT_MODEL: str = "scribe_v2"
    ELEVENLABS_API_TIMEOUT_SECONDS: float = 120.0

    # Audio cut snapping
    AUDIO_SNAPPING_ENABLED: bool = True
    SNAPPING_WINDOW_MS: int = 150
    SNAPPING_ENERGY_PERCENTILE: float = 20.0

    # Rendering defaults
    RENDER_VIDEO_CODEC: str = "libx264"
    RENDER_AUDIO_CODEC: str = "aac"
    RENDER_AUDIO_SAMPLE_RATE: int = 48000
    RENDER_CRF: int = 20
    RENDER_PRESET: str = "veryfast"
    RENDER_MAX_DIMENSION: int = 1920
    RENDER_TOLERANCE_SECONDS: float = 0.15

    def _find_winget_binary(self, executable: str) -> Optional[str]:
        """Search the common Windows package path without failing on restricted folders."""
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if not local_app_data:
            return None
        candidate_dir = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        try:
            if candidate_dir.exists():
                matches = candidate_dir.glob(f"**/{executable}")
                return next((str(path) for path in matches if path.is_file()), None)
        except OSError:
            # WinGet folders can be inaccessible in locked-down or sandboxed sessions.
            # Binary resolution should continue to PATH/default instead of aborting upload.
            return None
        return None

    def resolve_ffmpeg(self) -> str:
        """Resolve configured, project-local, PATH, or winget FFmpeg binaries."""
        if self.FFMPEG_BINARY:
            try:
                if Path(self.FFMPEG_BINARY).is_file():
                    return self.FFMPEG_BINARY
            except OSError:
                # A configured path can exist outside the current user's access
                # boundary. Continue discovery so readiness can report missing
                # FFmpeg instead of crashing while inspecting that path.
                pass
        project_binary = Path(__file__).resolve().parents[1] / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
        if project_binary.is_file():
            return str(project_binary)
        found = shutil.which("ffmpeg")
        if found:
            return found
        winget_binary = self._find_winget_binary("ffmpeg.exe")
        if winget_binary:
            return winget_binary
        return "ffmpeg"

    def resolve_ffprobe(self) -> str:
        """Resolve configured, project-local, PATH, or winget FFprobe binaries."""
        if self.FFPROBE_BINARY:
            try:
                if Path(self.FFPROBE_BINARY).is_file():
                    return self.FFPROBE_BINARY
            except OSError:
                # Match FFmpeg discovery behavior for unreadable configured paths.
                pass
        project_binary = Path(__file__).resolve().parents[1] / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
        if project_binary.is_file():
            return str(project_binary)
        found = shutil.which("ffprobe")
        if found:
            return found
        winget_binary = self._find_winget_binary("ffprobe.exe")
        if winget_binary:
            return winget_binary
        return "ffprobe"

    def ensure_directories(self) -> None:
        """Ensure all required local directories exist."""
        for d in [self.LOCAL_STORAGE_DIR, self.RENDER_OUTPUT_DIR, self.TEMP_DIR]:
            Path(d).mkdir(parents=True, exist_ok=True)
        # Ensure db dir exists if sqlite file
        if self.DATABASE_URL.startswith("sqlite:///"):
            db_path = Path(self.DATABASE_URL.replace("sqlite:///", ""))
            db_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
