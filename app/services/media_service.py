import json
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO, Dict, Optional
from app.config import settings
from app.models.db import MediaRecord, SessionLocal
from app.models.media import MediaManifest, MediaMetadata
from app.rendering.probe import probe_media_file
from app.storage.local import LocalStorageAdapter
from app.utils.security import (
    compute_sha256,
    generate_safe_media_id,
    sanitize_filename,
    validate_file_extension,
)

storage_adapter = LocalStorageAdapter()


class MediaServiceError(Exception):
    pass


class MediaService:
    def __init__(self):
        self.storage = storage_adapter

    def intake_uploaded_file(
        self,
        file_obj: BinaryIO,
        original_filename: str,
        content_length: Optional[int] = None,
    ) -> MediaManifest:
        # 1. Validate extension
        clean_orig_name = sanitize_filename(original_filename)
        ext = validate_file_extension(clean_orig_name)

        # 2. Check size limit
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if content_length and content_length > max_bytes:
            raise MediaServiceError(f"Upload size {content_length} bytes exceeds maximum limit of {settings.MAX_UPLOAD_SIZE_MB}MB")

        # 3. Save to isolated temporary file to compute hash
        temp_name = f"temp_{uuid.uuid4().hex[:8]}{ext}"
        storage_path_str = self.storage.save_file(file_obj, temp_name)
        storage_path = Path(storage_path_str)

        # 4. Check actual file size
        actual_size = storage_path.stat().st_size
        if actual_size > max_bytes:
            storage_path.unlink(missing_ok=True)
            raise MediaServiceError(f"File size {actual_size} bytes exceeds maximum limit of {settings.MAX_UPLOAD_SIZE_MB}MB")
        if actual_size == 0:
            storage_path.unlink(missing_ok=True)
            raise MediaServiceError("Uploaded file is empty (0 bytes).")

        # 5. Compute original media SHA-256 hash
        sha256_hash = compute_sha256(storage_path)

        # 6. Deterministic media ID from original media SHA-256 hash
        media_id = f"med_{sha256_hash[:12]}"
        storage_filename = f"{media_id}{ext}"
        final_storage_path = storage_path.parent / storage_filename

        # Move temp to deterministic filename if different
        if final_storage_path != storage_path:
            if final_storage_path.exists():
                storage_path.unlink()
            else:
                storage_path.rename(final_storage_path)
            storage_path = final_storage_path

        # 7. Probe with FFprobe
        try:
            metadata = probe_media_file(storage_path)
        except Exception as e:
            # Corrupt, unreadable, or invalid format -> reject and delete file
            storage_path.unlink(missing_ok=True)
            raise MediaServiceError(f"Media validation failed: {str(e)}")

        manifest = MediaManifest(
            media_id=media_id,
            original_filename=clean_orig_name,
            storage_filename=storage_filename,
            storage_path=str(storage_path.resolve()),
            file_size=actual_size,
            sha256_hash=sha256_hash,
            metadata=metadata,
        )

        # 8. Check if record already exists in DB (deduplication)
        db = SessionLocal()
        try:
            existing = db.query(MediaRecord).filter(MediaRecord.id == media_id).first()
            if existing:
                return MediaManifest.model_validate(json.loads(existing.metadata_json))

            record = MediaRecord(
                id=media_id,
                original_filename=clean_orig_name,
                storage_path=str(storage_path.resolve()),
                sha256_hash=sha256_hash,
                metadata_json=manifest.model_dump_json(),
            )
            db.add(record)
            db.commit()
        finally:
            db.close()

        return manifest

    def get_media_manifest(self, media_id: str) -> Optional[MediaManifest]:
        db = SessionLocal()
        try:
            rec = db.query(MediaRecord).filter(MediaRecord.id == media_id).first()
            if not rec:
                return None
            data = json.loads(rec.metadata_json)
            return MediaManifest.model_validate(data)
        finally:
            db.close()


media_service = MediaService()
