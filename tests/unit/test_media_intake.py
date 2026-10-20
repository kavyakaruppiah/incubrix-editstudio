import pytest
from types import SimpleNamespace
from pathlib import Path
from app.rendering import probe as media_probe
from app.rendering.probe import MediaProbeError, probe_media_file
from app.services.media_service import MediaServiceError, media_service
from app.utils.security import compute_sha256, safe_join_path, validate_file_extension

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_01_valid_media_metadata_extraction():
    """Scenario 1: Valid media metadata extraction via FFprobe."""
    media_path = FIXTURES_DIR / "sample_with_audio.mp4"
    meta = probe_media_file(media_path)
    assert meta.duration > 11.5
    assert meta.width == 320
    assert meta.height == 240
    assert meta.frame_rate == 30.0
    assert meta.audio_present is True
    assert meta.sample_rate == 48000
    assert meta.channels == 1
    assert meta.file_size > 0


def test_02_invalid_and_corrupt_media_rejection():
    """Scenario 2: Invalid, corrupt, and empty media rejection."""
    corrupt_path = FIXTURES_DIR / "corrupt_media.mp4"
    with pytest.raises(MediaProbeError):
        probe_media_file(corrupt_path)

    # Empty file
    empty_path = FIXTURES_DIR / "empty_test_file.mp4"
    empty_path.touch()
    try:
        with pytest.raises(MediaProbeError):
            probe_media_file(empty_path)
    finally:
        empty_path.unlink()

    # Path traversal attempt rejection
    with pytest.raises(ValueError):
        safe_join_path("data/storage", "../../etc/passwd")

    # Invalid extension
    with pytest.raises(ValueError):
        validate_file_extension("malicious.exe")


def test_03_original_media_hash_preservation():
    """Scenario 3: Original media SHA-256 calculation and preservation."""
    media_path = FIXTURES_DIR / "sample_with_audio.mp4"
    hash1 = compute_sha256(media_path)
    with open(media_path, "rb") as f:
        manifest = media_service.intake_uploaded_file(f, "sample_with_audio.mp4")
    assert manifest.sha256_hash == hash1
    # Check that original storage copy matches
    assert compute_sha256(manifest.storage_path) == hash1


def test_39_varying_frame_rate_metadata():
    """Scenario 39: Detecting and handling frame-rate metadata correctly."""
    media_path = FIXTURES_DIR / "sample_with_audio.mp4"
    meta = probe_media_file(media_path)
    assert isinstance(meta.is_vfr, bool)
    assert meta.frame_rate > 0


@pytest.mark.parametrize("stdout", [None, ""])
def test_ffprobe_missing_json_output_has_actionable_error(monkeypatch, tmp_path, stdout):
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    monkeypatch.setattr(type(media_probe.settings), "resolve_ffprobe", lambda self: "ffprobe")
    monkeypatch.setattr(
        media_probe.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )

    with pytest.raises(MediaProbeError, match="FFprobe returned no JSON metadata"):
        probe_media_file(media_path)
