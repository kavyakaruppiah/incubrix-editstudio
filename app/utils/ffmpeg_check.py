import subprocess
from typing import Dict, Tuple
from app.config import settings


def check_ffmpeg_and_ffprobe() -> Tuple[bool, Dict[str, str]]:
    """Verify that both ffmpeg and ffprobe binaries are reachable and executable."""
    ffmpeg_bin = settings.resolve_ffmpeg()
    ffprobe_bin = settings.resolve_ffprobe()

    info: Dict[str, str] = {
        "ffmpeg_binary": ffmpeg_bin,
        "ffprobe_binary": ffprobe_bin,
    }

    try:
        proc = subprocess.run([ffmpeg_bin, "-version"], capture_output=True, text=True, timeout=5)
        if proc.returncode != 0:
            info["ffmpeg_error"] = f"ffmpeg returned exit code {proc.returncode}"
            return False, info
        info["ffmpeg_version"] = proc.stdout.splitlines()[0] if proc.stdout else "unknown"
    except Exception as e:
        info["ffmpeg_error"] = str(e)
        return False, info

    try:
        proc = subprocess.run([ffprobe_bin, "-version"], capture_output=True, text=True, timeout=5)
        if proc.returncode != 0:
            info["ffprobe_error"] = f"ffprobe returned exit code {proc.returncode}"
            return False, info
        info["ffprobe_version"] = proc.stdout.splitlines()[0] if proc.stdout else "unknown"
    except Exception as e:
        info["ffprobe_error"] = str(e)
        return False, info

    return True, info
