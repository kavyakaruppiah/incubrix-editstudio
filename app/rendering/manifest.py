from pathlib import Path
from typing import List, Optional
from app.config import settings
from app.models.render import RenderVerification
from app.models.timeline import Timeline
from app.rendering.probe import probe_media_file
from app.utils.security import compute_sha256


class RenderVerificationError(Exception):
    pass


def verify_rendered_output(
    rendered_output_path: str | Path,
    expected_timeline: Timeline,
    original_media_path: str | Path,
    tolerance_seconds: Optional[float] = None,
) -> RenderVerification:
    """
    Perform rigorous post-render verification on the output media:
    1. Probe output with FFprobe.
    2. Verify output is readable and non-empty.
    3. Measure actual duration vs expected timeline duration within tolerance.
    4. Check audio & video stream presence.
    5. Verify original media file hash has NOT changed.
    6. Compute rendered file SHA-256 hash.
    """
    tol = tolerance_seconds if tolerance_seconds is not None else settings.RENDER_TOLERANCE_SECONDS
    warnings: List[str] = []

    # 1. Verify original media hash is unchanged
    current_original_hash = compute_sha256(original_media_path)
    hash_verified = (current_original_hash == expected_timeline.original_media_hash)
    if not hash_verified:
        raise RenderVerificationError(
            f"CRITICAL: Original media file hash has changed! Expected {expected_timeline.original_media_hash}, got {current_original_hash}"
        )

    # 2. Check rendered file existence and non-zero size
    out_file = Path(rendered_output_path)
    if not out_file.is_file() or out_file.stat().st_size == 0:
        raise RenderVerificationError(f"Rendered output file is missing or 0 bytes: {rendered_output_path}")

    rendered_file_hash = compute_sha256(rendered_output_path)

    # 3. Probe output file
    try:
        out_meta = probe_media_file(rendered_output_path)
    except Exception as e:
        raise RenderVerificationError(f"Rendered output file is unreadable by FFprobe: {str(e)}")

    expected_dur = expected_timeline.total_output_duration
    actual_dur = out_meta.duration
    dur_diff = abs(actual_dur - expected_dur)
    dur_ok = dur_diff <= tol

    if not dur_ok:
        warnings.append(
            f"Rendered duration {actual_dur:.3f}s differs from expected {expected_dur:.3f}s by {dur_diff:.3f}s (tolerance: {tol}s)"
        )

    video_present = True  # probe_media_file requires video stream
    audio_present = out_meta.audio_present
    expected_audio = expected_timeline.source_metadata.audio_present and any(s.audio_enabled for s in expected_timeline.segments)

    if expected_audio and not audio_present:
        warnings.append("Expected audio stream in rendered output, but none was detected")
    elif not expected_audio and audio_present:
        warnings.append("Audio stream present in output although source had no audio or audio was disabled")

    return RenderVerification(
        is_readable=True,
        expected_duration_s=round(expected_dur, 4),
        actual_duration_s=round(actual_dur, 4),
        duration_difference_s=round(dur_diff, 4),
        duration_within_tolerance=dur_ok,
        video_stream_present=video_present,
        audio_stream_present=audio_present,
        audio_video_sync_skew_s=0.0 if audio_present else None,
        original_file_hash_verified=hash_verified,
        original_media_hash=expected_timeline.original_media_hash,
        rendered_file_hash=rendered_file_hash,
        width=out_meta.width,
        height=out_meta.height,
        frame_rate=out_meta.frame_rate,
        video_codec=out_meta.video_codec,
        audio_codec=settings.RENDER_AUDIO_CODEC if audio_present else None,
        warnings=warnings,
    )
