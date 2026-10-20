import shutil
from pathlib import Path
from typing import BinaryIO
from app.config import settings
from app.storage.base import StorageAdapter
from app.utils.security import safe_join_path, sanitize_filename


class LocalStorageAdapter(StorageAdapter):
    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir or settings.LOCAL_STORAGE_DIR).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_file(self, file_obj: BinaryIO, destination_name: str) -> str:
        clean_name = sanitize_filename(destination_name)
        target_path = safe_join_path(self.base_dir, clean_name)
        with open(target_path, "wb") as f:
            shutil.copyfileobj(file_obj, f)
        return str(target_path.resolve())

    def get_local_path(self, storage_identifier: str) -> Path:
        # Check if already an absolute path
        p = Path(storage_identifier)
        if p.is_absolute() and p.exists():
            return p
        return safe_join_path(self.base_dir, storage_identifier)

    def exists(self, storage_identifier: str) -> bool:
        try:
            p = self.get_local_path(storage_identifier)
            return p.is_file()
        except Exception:
            return False

    def delete(self, storage_identifier: str) -> bool:
        try:
            p = self.get_local_path(storage_identifier)
            if p.is_file():
                p.unlink()
                return True
            return False
        except Exception:
            return False
