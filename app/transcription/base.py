from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from app.models.transcript import Transcript


class TranscriptionAdapter(ABC):
    """Abstract interface for transcription adapters."""

    @abstractmethod
    def is_available(self) -> Tuple[bool, str]:
        """Return (is_available, status_message_or_download_instruction)."""
        pass

    @abstractmethod
    def transcribe(self, media_path: str, language: Optional[str] = "en") -> Transcript:
        """Transcribe media file to word-level Transcript model."""
        pass
