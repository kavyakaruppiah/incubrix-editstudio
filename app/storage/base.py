from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional


class StorageAdapter(ABC):
    """Abstract interface for media file storage."""

    @abstractmethod
    def save_file(self, file_obj: BinaryIO, destination_name: str) -> str:
        """Save file stream and return its absolute or canonical path/URL."""
        pass

    @abstractmethod
    def get_local_path(self, storage_identifier: str) -> Path:
        """Return a local Path accessible to FFmpeg/FFprobe."""
        pass

    @abstractmethod
    def exists(self, storage_identifier: str) -> bool:
        """Check if file exists in storage."""
        pass

    @abstractmethod
    def delete(self, storage_identifier: str) -> bool:
        """Delete file from storage."""
        pass
