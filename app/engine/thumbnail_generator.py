"""
Thumbnail generation service using FFmpeg with disk caching.
Generates representative poster frames and preview thumbnails for media assets.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger("app.engine.thumbnail_generator")


def generate_thumbnail(
    video_path: str | Path,
    output_path: Optional[str | Path] = None,
    timestamp_s: float = 1.0,
    width: int = 320,
    force_refresh: bool = False,
) -> Path:
    """
    Generate a JPEG thumbnail from a video file at the requested timestamp.
    Caches the generated JPEG on disk.
    """
    v_path = Path(video_path).resolve()
    if not v_path.is_file():
        raise FileNotFoundError(f"Source video not found: {video_path}")

    if output_path is None:
        thumbs_dir = Path(settings.LOCAL_STORAGE_DIR) / "thumbnails"
        thumbs_dir.mkdir(parents=True, exist_ok=True)
        out_file = thumbs_dir / f"{v_path.stem}_thumb.jpg"
    else:
        out_file = Path(output_path).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)

    if not force_refresh and out_file.is_file() and out_file.stat().st_size > 0:
        return out_file

    ffmpeg_bin = settings.resolve_ffmpeg()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss", str(max(0.0, timestamp_s)),
        "-i", str(v_path),
        "-vframes", "1",
        "-vf", f"scale={width}:-1",
        "-q:v", "3",
        str(out_file),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0 or not out_file.is_file() or out_file.stat().st_size == 0:
            logger.warning(f"FFmpeg thumbnail extraction failed (code {proc.returncode}): {proc.stderr}")
            # Try at 0.0s if requested timestamp was beyond duration
            if timestamp_s > 0.1:
                return generate_thumbnail(video_path, out_file, timestamp_s=0.0, width=width, force_refresh=True)
            raise RuntimeError(f"FFmpeg failed to generate thumbnail: {proc.stderr}")
        return out_file
    except subprocess.TimeoutExpired:
        raise TimeoutError("Thumbnail generation timed out after 15 seconds.")
