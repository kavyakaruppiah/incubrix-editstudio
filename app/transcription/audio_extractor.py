import subprocess
import uuid
from pathlib import Path
from typing import Optional
from app.config import settings
from app.rendering.probe import probe_media_file


class AudioExtractionError(Exception):
    pass


def extract_voice_audio(
    video_path: str | Path,
    output_wav_path: Optional[str | Path] = None,
    filter_noise: bool = True,
) -> Optional[Path]:
    """
    Extracts speech-optimized 16kHz mono 16-bit PCM WAV audio from any video file.
    Returns None if the video has no audio stream.
    """
    v_path = Path(video_path)
    if not v_path.is_file():
        raise AudioExtractionError(f"Video file not found: {video_path}")

    # 1. Probe for audio stream presence
    try:
        metadata = probe_media_file(v_path)
        if not metadata.audio_present:
            return None
    except Exception:
        # If probe fails, continue to attempt extraction
        pass

    # 2. Destination WAV file
    if output_wav_path:
        out_p = Path(output_wav_path)
    else:
        temp_dir = Path(settings.RENDER_OUTPUT_DIR) / "extracted_audio"
        temp_dir.mkdir(parents=True, exist_ok=True)
        out_p = temp_dir / f"voice_{uuid.uuid4().hex[:8]}.wav"

    ffmpeg_bin = settings.resolve_ffmpeg()

    # 3. Build FFmpeg command for pristine voice extraction
    # 16kHz sample rate, 1 channel mono, 16-bit PCM
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(v_path.resolve()),
        "-vn",
    ]

    if filter_noise:
        # Highpass cuts mic thumps (<60Hz), maintains speech intelligibility
        cmd.extend(["-af", "highpass=f=60,volume=1.0"])

    cmd.extend([
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(out_p.resolve()),
    ])

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if res.returncode != 0:
            # Check if failure was due to no audio stream
            if "does not contain any stream" in res.stderr.lower():
                return None
            # Fallback without audio filter if filter failed
            cmd_simple = [
                ffmpeg_bin, "-y", "-i", str(v_path.resolve()),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(out_p.resolve()),
            ]
            res2 = subprocess.run(cmd_simple, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if res2.returncode != 0:
                details = (res2.stderr or res.stderr or "FFmpeg could not decode the audio stream.").strip()
                raise AudioExtractionError(f"Audio extraction failed: {details[-1200:]}")

        if out_p.is_file() and out_p.stat().st_size > 100:
            return out_p
        raise AudioExtractionError("FFmpeg completed but produced no usable audio file.")
    except subprocess.TimeoutExpired as exc:
        raise AudioExtractionError("Audio extraction timed out. Try a shorter video or a smaller upload.") from exc
    except AudioExtractionError:
        raise
    except Exception as exc:
        raise AudioExtractionError(f"Audio extraction failed: {exc}") from exc
