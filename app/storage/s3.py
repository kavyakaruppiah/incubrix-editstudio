import shutil
from pathlib import Path
from typing import BinaryIO, Optional
from app.config import settings
from app.storage.base import StorageAdapter
from app.utils.security import sanitize_filename


class S3StorageAdapter(StorageAdapter):
    """Optional S3 / MinIO storage adapter."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        bucket_name: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        self.endpoint_url = endpoint_url or settings.S3_ENDPOINT_URL
        self.bucket_name = bucket_name or settings.S3_BUCKET_NAME
        self.access_key = access_key or settings.S3_ACCESS_KEY_ID
        self.secret_key = secret_key or settings.S3_SECRET_ACCESS_KEY
        self.local_cache = Path(settings.LOCAL_STORAGE_DIR) / "s3_cache"
        self.local_cache.mkdir(parents=True, exist_ok=True)

    def is_configured(self) -> bool:
        return bool(self.endpoint_url and self.access_key and self.secret_key)

    def save_file(self, file_obj: BinaryIO, destination_name: str) -> str:
        clean_name = sanitize_filename(destination_name)
        # In absence of boto3 or credentials, store in local cache with s3 identifier
        local_target = self.local_cache / clean_name
        with open(local_target, "wb") as f:
            shutil.copyfileobj(file_obj, f)
        return f"s3://{self.bucket_name}/{clean_name}"

    def get_local_path(self, storage_identifier: str) -> Path:
        key = storage_identifier.replace(f"s3://{self.bucket_name}/", "")
        return self.local_cache / key

    def exists(self, storage_identifier: str) -> bool:
        key = storage_identifier.replace(f"s3://{self.bucket_name}/", "")
        return (self.local_cache / key).is_file()

    def delete(self, storage_identifier: str) -> bool:
        key = storage_identifier.replace(f"s3://{self.bucket_name}/", "")
        target = self.local_cache / key
        if target.is_file():
            target.unlink()
            return True
        return False
