"""Small OTIO JSON serializer for the engine's source-referenced timeline."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models.timeline import Timeline


def _rt(seconds: float) -> dict[str, Any]:
    # Seconds are used as the rational-time rate to avoid inventing a frame rate
    # for VFR media. OTIO consumers can convert to their preferred rate.
    return {"OTIO_SCHEMA": "RationalTime.1", "value": round(seconds, 9), "rate": 1.0}


def _track(timeline: Timeline, media_url: str, kind: str) -> dict[str, Any]:
    children = []
    for segment in timeline.segments:
        enabled = segment.video_enabled if kind == "Video" else segment.audio_enabled
        if not enabled:
            continue
        clip: dict[str, Any] = {
            "OTIO_SCHEMA": "Clip.2",
            "name": segment.label or segment.segment_id,
            "media_reference": {
                "OTIO_SCHEMA": "ExternalReference.1",
                "name": Path(media_url).name,
                "target_url": media_url,
                "available_range": {
                    "OTIO_SCHEMA": "TimeRange.1",
                    "start_time": _rt(0),
                    "duration": _rt(timeline.source_metadata.duration),
                },
                "metadata": {},
            },
            "source_range": {
                "OTIO_SCHEMA": "TimeRange.1",
                "start_time": _rt(segment.source_start),
                "duration": _rt(segment.source_duration),
            },
            "metadata": {"incubrix": {"segment_id": segment.segment_id, "speed": segment.speed}},
            "effects": [],
            "markers": [],
            "enabled": True,
        }
        if segment.speed != 1.0:
            clip["effects"].append({
                "OTIO_SCHEMA": "LinearTimeWarp.1",
                "name": "IncuBrix speed",
                "time_scalar": segment.speed,
                "metadata": {},
            })
        children.append(clip)
    return {
        "OTIO_SCHEMA": "Track.1",
        "name": kind,
        "kind": kind,
        "children": children,
        "metadata": {},
    }


def timeline_to_otio(timeline: Timeline, source_path: str) -> dict[str, Any]:
    """Return an OTIO serialized-schema document with source-linked A/V tracks."""
    path = Path(source_path).resolve()
    # file:// URLs are portable across JSON and correctly escape spaces/non-ASCII.
    media_url = path.as_uri()
    warnings = []
    if any(s.transition_in in {"crossfade", "dissolve"} for s in timeline.segments[1:]):
        warnings.append("Clip transitions are recorded in IncuBrix metadata; OTIO transition objects are not emitted yet.")
    if timeline.video_effects.model_dump(exclude_defaults=True) or timeline.audio_effects.model_dump(exclude_defaults=True):
        warnings.append("Global IncuBrix effects are preserved as metadata; OTIO native effect translation is incomplete.")
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": f"IncuBrix {timeline.media_id}",
        "global_start_time": _rt(0),
        "metadata": {
            "incubrix": {
                "schema_version": timeline.schema_version,
                "media_id": timeline.media_id,
                "revision": timeline.revision,
                "timeline_hash": timeline.original_media_hash,
                "transitions": [
                    {"segment_id": s.segment_id, "type": s.transition_in, "duration": s.transition_duration}
                    for s in timeline.segments[1:] if s.transition_in != "cut"
                ],
                "captions": [c.model_dump(mode="json") for c in timeline.captions],
                "text_overlays": [o.model_dump(mode="json") for o in timeline.text_overlays],
                "audio_effects": timeline.audio_effects.model_dump(mode="json"),
                "video_effects": timeline.video_effects.model_dump(mode="json"),
                "warnings": warnings,
            }
        },
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "children": [_track(timeline, media_url, "Video"), _track(timeline, media_url, "Audio")],
            "metadata": {},
        },
    }
