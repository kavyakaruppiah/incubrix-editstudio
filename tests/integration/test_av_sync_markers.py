"""End-to-end A/V sync check using paired visual flashes and audio impulses."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from app.config import settings
from app.models.timeline import Timeline, TimelineSegment
from app.rendering.ffmpeg_renderer import render_timeline
from app.rendering.probe import probe_media_file
from app.utils.security import compute_sha256


def _make_marker_source(path: Path) -> None:
    video_filter = (
        "color=c=black:s=160x90:r=30:d=8,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:"
        "enable='gte(mod(n,60),30)*lt(mod(n,60),32)'"
    )
    audio_source = "aevalsrc=exprs='if(gte(t,1)*lt(mod(t-1,2),0.01),0.8,0)':s=48000:d=8"
    command = [
        settings.resolve_ffmpeg(), "-y",
        "-f", "lavfi", "-i", video_filter,
        "-f", "lavfi", "-i", audio_source,
        "-map", "0:v:0", "-map", "1:a:0", "-t", "8",
        "-c:v", "ffv1", "-c:a", "pcm_s16le", str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if completed.returncode != 0:
        raise AssertionError(f"Could not create A/V sync marker fixture: {completed.stderr[-2000:]}")


def _decode_video_frame_times(path: Path, width: int, height: int) -> list[float]:
    command = [
        settings.resolve_ffmpeg(), "-v", "error", "-i", str(path), "-an",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    decoded = subprocess.run(command, capture_output=True, timeout=30, check=True).stdout
    frame_size = width * height
    frame_count = len(decoded) // frame_size
    frames = np.frombuffer(decoded[:frame_count * frame_size], dtype=np.uint8).reshape(frame_count, frame_size)
    return [index / 30.0 for index, frame in enumerate(frames) if float(frame.mean()) > 150.0]


def _decode_audio_click_times(path: Path) -> list[float]:
    command = [
        settings.resolve_ffmpeg(), "-v", "error", "-i", str(path), "-vn",
        "-f", "s16le", "-ac", "1", "-ar", "48000", "pipe:1",
    ]
    decoded = subprocess.run(command, capture_output=True, timeout=30, check=True).stdout
    samples = np.frombuffer(decoded, dtype=np.int16).astype(np.float32)
    window = 240  # 5 ms at 48 kHz
    usable = len(samples) // window * window
    rms = np.sqrt(np.mean(samples[:usable].reshape(-1, window) ** 2, axis=1))
    active = np.flatnonzero(rms > 1800.0)
    if not len(active):
        return []
    groups = [[int(active[0])]]
    for idx in active[1:]:
        if int(idx) - groups[-1][-1] <= 2:
            groups[-1].append(int(idx))
        else:
            groups.append([int(idx)])
    return [
        max(group, key=lambda idx: rms[idx]) * window / 48000.0 + window / 96000.0
        for group in groups
    ]


def test_rendered_video_flashes_and_audio_clicks_stay_within_one_frame(tmp_path):
    source = tmp_path / "sync_markers.mkv"
    _make_marker_source(source)
    metadata = probe_media_file(source)
    timeline = Timeline(
        media_id="sync-marker-test",
        original_media_hash=compute_sha256(source),
        source_metadata=metadata,
        segments=[
            TimelineSegment(segment_id="fast", source_start=0, source_end=4, speed=2.0),
            TimelineSegment(segment_id="normal", source_start=4, source_end=8, speed=1.0),
        ],
    )

    manifest = render_timeline(timeline, str(source), output_dir=str(tmp_path))
    output = Path(manifest.output_path)
    verification = manifest.verification
    assert verification is not None and verification.duration_within_tolerance
    flash_times = _decode_video_frame_times(output, verification.width, verification.height)
    click_times = _decode_audio_click_times(output)
    # AAC decoding may spread an impulse over adjacent frames; group both event
    # sets by the nearest expected source-marker output time.
    expected = [0.5, 1.5, 3.0, 5.0]
    frame_rate = timeline.source_metadata.frame_rate
    tolerance = 1.0 / frame_rate + 0.002
    flash_groups = []
    for timestamp in flash_times:
        if flash_groups and timestamp - flash_groups[-1][-1] <= 1.01 / 30.0:
            flash_groups[-1].append(timestamp)
        else:
            flash_groups.append([timestamp])
    flash_events = [sum(group) / len(group) for group in flash_groups]
    assert len(flash_events) == len(expected), f"Expected four decoded visual markers, got {flash_times}"
    assert len(click_times) == len(expected), f"Expected four decoded clicks, got {click_times}"
    for target, flash, click in zip(expected, flash_events, click_times):
        assert abs(flash - target) <= tolerance, (target, flash)
        assert abs(click - target) <= tolerance, (target, click)
        assert abs(flash - click) <= tolerance, (flash, click)
