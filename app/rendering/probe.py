import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
from app.config import settings
from app.models.media import MediaMetadata


class MediaProbeError(Exception):
    pass


def parse_fraction(val: Optional[str]) -> float:
    """Parse string fraction e.g. '30000/1001' or '30/1' to float."""
    if not val:
        return 0.0
    if "/" in val:
        parts = val.split("/")
        try:
            num = float(parts[0])
            den = float(parts[1])
            return num / den if den != 0 else 0.0
        except ValueError:
            return 0.0
    try:
        return float(val)
    except ValueError:
        return 0.0


def probe_media_file(filepath: str | Path) -> MediaMetadata:
    """
    Use FFprobe to extract media metadata.
    Validates presence of a valid, readable video stream.
    Gracefully handles absence of audio stream and detects VFR.
    """
    p = Path(filepath)
    if not p.is_file():
        raise MediaProbeError(f"Media file does not exist or is inaccessible: {filepath}")

    file_size = p.stat().st_size
    if file_size == 0:
        raise MediaProbeError("Media file is empty (0 bytes).")

    try:
        ffprobe_bin = settings.resolve_ffprobe()
        cmd = [
            ffprobe_bin,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(p.resolve()),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            raise MediaProbeError(
                f"FFprobe failed to inspect media (exit code {proc.returncode}): "
                f"{stderr or 'FFprobe returned no diagnostic output.'}"
            )
        stdout = proc.stdout
        if not isinstance(stdout, (str, bytes, bytearray)) or not stdout.strip():
            raise MediaProbeError(
                "FFprobe returned no JSON metadata. Check that FFprobe is installed and "
                "the uploaded file is a readable video."
            )
        data = json.loads(stdout)
        if not isinstance(data, dict):
            raise MediaProbeError("FFprobe returned invalid metadata: expected a JSON object.")
    except subprocess.TimeoutExpired:
        raise MediaProbeError("FFprobe inspection timed out after 10 seconds.")
    except MediaProbeError:
        raise
    except json.JSONDecodeError as e:
        raise MediaProbeError(f"Failed to parse FFprobe JSON output: {str(e)}")
    except Exception as e:
        raise MediaProbeError(f"Failed to execute FFprobe: {str(e)}")

    streams = data.get("streams", [])
    format_info = data.get("format", {})
    if not isinstance(streams, list) or not isinstance(format_info, dict):
        raise MediaProbeError("FFprobe returned malformed stream or format metadata.")

    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if not video_streams:
        raise MediaProbeError("No readable video stream found in media file. Supported formats: MP4, MOV with video.")

    v_stream = video_streams[0]

    # Width and Height
    width = v_stream.get("width")
    height = v_stream.get("height")
    if not width or not height or width <= 0 or height <= 0:
        raise MediaProbeError(f"Corrupt or invalid video dimensions: {width}x{height}")

    # Duration
    duration_str = v_stream.get("duration") or format_info.get("duration")
    if not duration_str:
        raise MediaProbeError("Unable to determine media duration.")
    try:
        duration = float(duration_str)
        if duration <= 0:
            raise MediaProbeError(f"Invalid media duration: {duration}s")
    except ValueError:
        raise MediaProbeError(f"Unparseable duration value: {duration_str}")

    # Frame Rate and VFR detection
    r_fps = parse_fraction(v_stream.get("r_frame_rate"))
    avg_fps = parse_fraction(v_stream.get("avg_frame_rate"))
    fps = avg_fps if avg_fps > 0 else (r_fps if r_fps > 0 else 30.0)

    # Detect variable frame rate if r_frame_rate and avg_frame_rate differ by more than 0.5%
    is_vfr = False
    if r_fps > 0 and avg_fps > 0:
        diff_ratio = abs(r_fps - avg_fps) / max(r_fps, avg_fps)
        if diff_ratio > 0.005:
            is_vfr = True

    video_codec = v_stream.get("codec_name", "unknown")

    # Audio stream handling
    audio_present = len(audio_streams) > 0
    sample_rate: Optional[int] = None
    channels: Optional[int] = None

    if audio_present:
        a_stream = audio_streams[0]
        sr_val = a_stream.get("sample_rate")
        if sr_val:
            try:
                sample_rate = int(sr_val)
            except ValueError:
                sample_rate = 44100
        channels = a_stream.get("channels")

    return MediaMetadata(
        duration=round(duration, 4),
        width=int(width),
        height=int(height),
        frame_rate=round(fps, 4),
        video_codec=video_codec,
        audio_present=audio_present,
        sample_rate=sample_rate,
        channels=channels,
        is_vfr=is_vfr,
        file_size=file_size,
    )
