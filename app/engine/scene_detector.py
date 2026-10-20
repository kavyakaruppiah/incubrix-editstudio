"""
Scene detection engine using PySceneDetect with graceful fallback and local caching.
Supports automatic scene-based cutting, highlight generation, and montage creation.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("app.engine.scene_detector")


def detect_scenes(
    video_path: str | Path,
    threshold: float = 27.0,
    min_scene_len_seconds: float = 1.0,
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """
    Detect scenes in a video file using PySceneDetect (ContentDetector).
    Results are cached in a sidecar `.scenes.json` file to avoid expensive re-analysis.
    Returns a list of scene dictionaries with start/end seconds and timecodes.
    """
    p = Path(video_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    cache_file = p.parent / f"{p.stem}.scenes.json"
    if not force_refresh and cache_file.is_file():
        try:
            cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached_data, list) and len(cached_data) > 0:
                logger.info(f"Loaded {len(cached_data)} cached scenes for {p.name}")
                return cached_data
        except Exception as e:
            logger.warning(f"Failed to read scene cache for {p.name}: {e}")

    scenes: List[Dict[str, Any]] = []

    try:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import ContentDetector

        video = open_video(str(p))
        fps = video.frame_rate or 30.0
        min_scene_len_frames = max(1, int(min_scene_len_seconds * fps))

        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len_frames))
        scene_manager.detect_scenes(video=video)

        scene_list = scene_manager.get_scene_list()

        for idx, (start_time, end_time) in enumerate(scene_list, start=1):
            start_sec = round(start_time.get_seconds(), 3)
            end_sec = round(end_time.get_seconds(), 3)
            dur_sec = round(end_sec - start_sec, 3)
            scenes.append({
                "scene_number": idx,
                "start_seconds": start_sec,
                "end_seconds": end_sec,
                "duration_seconds": dur_sec,
                "start_timecode": str(start_time.get_timecode()),
                "end_timecode": str(end_time.get_timecode()),
            })

        logger.info(f"PySceneDetect detected {len(scenes)} scenes in {p.name}")

    except Exception as exc:
        logger.warning(f"PySceneDetect failed on {p.name}: {exc}. Using fallback single scene.")

    # Fallback if no cut was detected or scenedetect produced nothing
    if not scenes:
        try:
            from app.rendering.probe import probe_media_file
            meta = probe_media_file(p)
            dur = meta.duration
        except Exception:
            dur = 10.0

        scenes = [{
            "scene_number": 1,
            "start_seconds": 0.0,
            "end_seconds": round(dur, 3),
            "duration_seconds": round(dur, 3),
            "start_timecode": "00:00:00.000",
            "end_timecode": f"00:00:{dur:06.3f}",
        }]

    # Write cache
    try:
        cache_file.write_text(json.dumps(scenes, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to write scene cache to {cache_file}: {e}")

    return scenes
