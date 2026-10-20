import hashlib
import json
import math
import re
from decimal import Decimal
from typing import Any

# Runtime-only fields and generated IDs do not describe timeline content.
EXCLUDED_VOLATILE_FIELDS = {
    "created_at", "updated_at", "timestamp", "modified_at", "edited_at",
    "job_id", "correlation_id", "request_id",
    "render_id", "rendered_outputs", "warnings", "operation_id", "segment_id",
    "media_id", "caption_id", "overlay_id", "mute_id", "bleep_id",
}

_GENERATED_ID = re.compile(
    r"^(?:(?:seg|cap|op|mute|bleep|ovl|req|rnd)_[0-9a-f]{8,}|"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


def sanitize_for_canonical(data: Any) -> Any:
    """Return stable JSON data with no floats, timestamps, or generated IDs."""
    if isinstance(data, dict):
        return {
            key: sanitize_for_canonical(value)
            for key, value in sorted(data.items(), key=lambda item: item[0])
            if key not in EXCLUDED_VOLATILE_FIELDS
        }
    if isinstance(data, (list, tuple)):
        return [sanitize_for_canonical(item) for item in data]
    if isinstance(data, float):
        if not math.isfinite(data):
            raise ValueError("timeline hash cannot contain NaN or infinity")
        # The legacy schema still exposes float seconds. Normalize them to
        # microsecond precision and encode as strings, never JSON numbers.
        rounded = Decimal(str(round(data, 6)))
        return "0" if rounded == 0 else format(rounded.normalize(), "f")
    if isinstance(data, Decimal):
        if not data.is_finite():
            raise ValueError("timeline hash cannot contain NaN or infinity")
        return "0" if data == 0 else format(data.normalize(), "f")
    if isinstance(data, str) and _GENERATED_ID.fullmatch(data):
        return "<generated-id>"
    return data


def canonical_serialize(timeline_dict: dict) -> str:
    """Produce compact, key-sorted canonical JSON for a timeline."""
    sanitized = sanitize_for_canonical(timeline_dict)
    return json.dumps(sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_timeline_hash(timeline_dict: dict) -> str:
    """Compute deterministic SHA-256 over canonical timeline state."""
    canonical_str = canonical_serialize(timeline_dict)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
