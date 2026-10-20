import json

import pytest

from app.engine.canonical_hash import canonical_serialize, compute_timeline_hash


def _contains_float(value):
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_float(child) for child in value)
    return False


def test_canonical_json_encodes_legacy_float_values_as_decimal_strings():
    canonical = canonical_serialize({"start": 1.25, "speed": 1.5, "nested": [0.0, -0.0]})

    assert not _contains_float(json.loads(canonical))
    assert json.loads(canonical) == {"nested": ["0", "0"], "speed": "1.5", "start": "1.25"}


def test_generated_ids_and_timestamps_do_not_change_timeline_hash():
    first = {
        "segment_id": "seg_0123456789abcdef",
        "caption_id": "cap_01234567",
        "created_at": "2026-10-19T10:00:00Z",
        "source_start": 3.125,
        "caption": "Keep this sentence",
    }
    second = {
        **first,
        "segment_id": "seg_fedcba9876543210",
        "caption_id": "cap_fedcba98",
        "created_at": "2026-10-20T10:00:00Z",
    }

    assert compute_timeline_hash(first) == compute_timeline_hash(second)


def test_non_finite_float_is_rejected_from_hash():
    with pytest.raises(ValueError, match="NaN or infinity"):
        canonical_serialize({"speed": float("nan")})
