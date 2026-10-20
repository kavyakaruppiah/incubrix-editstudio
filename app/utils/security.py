import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Tuple


def compute_sha256(filepath: str | Path, block_size: int = 65536) -> str:
    """Compute SHA-256 hash of a file deterministically in chunks."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for block in iter(lambda: f.read(block_size), b""):
            sha256.update(block)
    return sha256.hexdigest()


def generate_safe_media_id() -> str:
    """Generate a clean, collision-free media identifier."""
    return f"med_{uuid.uuid4().hex[:12]}"


def sanitize_filename(filename: str) -> str:
    """Remove unsafe characters and directory traversal markers from filename."""
    # Strip any paths
    clean = os.path.basename(filename)
    # Remove null bytes and non-alphanumeric/dot/hyphen/underscore
    clean = re.sub(r"[^\w\.\-]", "_", clean)
    if not clean or clean.startswith("."):
        clean = f"media_{uuid.uuid4().hex[:8]}"
    return clean


def safe_join_path(base_dir: str | Path, relative_path: str) -> Path:
    """Safely resolve relative_path within base_dir, strictly preventing path traversal."""
    base = Path(base_dir).resolve()
    # Normalize separators
    target = (base / relative_path).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError(f"Path traversal detected: {relative_path} attempts to escape {base_dir}")
    return target


def validate_file_extension(filename: str, allowed_extensions: Tuple[str, ...] = (".mp4", ".mov", ".m4v")) -> str:
    """Ensure file extension is allowed."""
    ext = Path(filename).suffix.lower()
    if ext not in allowed_extensions:
        raise ValueError(f"Unsupported file extension '{ext}'. Allowed extensions: {', '.join(allowed_extensions)}")
    return ext
