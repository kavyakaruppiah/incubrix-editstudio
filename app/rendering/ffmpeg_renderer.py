import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from app.config import settings
from app.engine.canonical_hash import compute_timeline_hash
from app.models.render import JobStatus, RenderManifest
from app.models.timeline import Timeline
from app.rendering.manifest import verify_rendered_output
from app.rendering.plan_builder import build_render_plan
from app.utils.logger import get_logger

logger = get_logger(__name__)


class FFmpegRenderingError(Exception):
    pass


def render_timeline(
    timeline: Timeline,
    media_source_path: str,
    output_dir: Optional[str] = None,
    render_id: Optional[str] = None,
    quality: Optional[int] = None,
    preset: Optional[str] = None,
    frame_rate: int = 30,
    cancel_event: Optional[threading.Event] = None,
) -> RenderManifest:
    """
    Execute real FFmpeg rendering from a validated Timeline.
    Never uses fake renders or mocked outputs.
    """
    r_id = render_id or f"rnd_{uuid.uuid4().hex[:12]}"
    out_dir = Path(output_dir or settings.RENDER_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    output_filename = f"render_{timeline.media_id}_rev{timeline.revision}_{r_id}.mp4"
    output_path = out_dir / output_filename
    temp_dir = Path(settings.TEMP_DIR) / r_id

    # Compute timeline hash
    tl_hash = compute_timeline_hash(timeline.model_dump())

    # Build plan
    plan = build_render_plan(
        timeline, media_source_path, str(output_path.resolve()), temp_dir,
        quality=quality, preset=preset, frame_rate=frame_rate,
    )
    logger.info(f"Starting FFmpeg render job {r_id} with command: {' '.join(plan.command)}")

    start_time = datetime.now(timezone.utc).isoformat()
    try:
        proc = subprocess.Popen(
            plan.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        started = time.monotonic()
        stdout = stderr = ""
        while True:
            if cancel_event and cancel_event.is_set():
                proc.terminate()
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, stderr = proc.communicate()
                raise FFmpegRenderingError("Rendering cancelled by user")
            if time.monotonic() - started > 120:
                proc.kill()
                stdout, stderr = proc.communicate()
                raise subprocess.TimeoutExpired(plan.command, 120)
            try:
                stdout, stderr = proc.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
        if proc.returncode != 0:
            exit_code = proc.returncode
            if 0x80000000 <= exit_code <= 0xFFFFFFFF:
                exit_code -= 0x100000000
            error_msg = f"FFmpeg execution failed (code {exit_code}): {stderr[-2000:] if stderr else 'No stderr'}"
            logger.error(error_msg)
            raise FFmpegRenderingError(error_msg)

        if cancel_event and cancel_event.is_set():
            output_path.unlink(missing_ok=True)
            raise FFmpegRenderingError("Rendering cancelled by user")

        # Post-render verification
        verification = verify_rendered_output(
            rendered_output_path=output_path,
            expected_timeline=timeline,
            original_media_path=media_source_path,
        )
        if cancel_event and cancel_event.is_set():
            output_path.unlink(missing_ok=True)
            raise FFmpegRenderingError("Rendering cancelled by user")

        completed_time = datetime.now(timezone.utc).isoformat()
        file_size = output_path.stat().st_size

        manifest = RenderManifest(
            render_id=r_id,
            media_id=timeline.media_id,
            timeline_revision=timeline.revision,
            timeline_hash=tl_hash,
            status=JobStatus.COMPLETED,
            created_at=start_time,
            completed_at=completed_time,
            output_filename=output_filename,
            output_path=str(output_path.resolve()),
            output_url=f"/api/v1/render/download/{output_filename}",
            file_size_bytes=file_size,
            ffmpeg_command=plan.command,
            verification=verification,
            extra_metadata={"quality": quality if quality is not None else settings.RENDER_CRF,
                            "preset": preset or settings.RENDER_PRESET, "frame_rate": frame_rate},
        )
        logger.info(f"Render completed successfully for {r_id}, size: {file_size} bytes")
        return manifest

    except subprocess.TimeoutExpired:
        raise FFmpegRenderingError(f"Rendering job {r_id} timed out after 120 seconds")
    except FFmpegRenderingError as exc:
        if "cancelled" in str(exc).lower():
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        # Clean up temporary subtitle and scratch files
        for tf in plan.temp_files:
            try:
                if tf.exists():
                    tf.unlink()
            except Exception:
                pass
        try:
            if temp_dir.exists():
                for f in temp_dir.glob("*"):
                    f.unlink()
                temp_dir.rmdir()
        except Exception:
            pass
