from pathlib import Path
import json
from app.engine.timeline_engine import TimelineEngine
from app.models.media import MediaMetadata
from app.models.timeline import Timeline, TimelineSegment
from app.transcription.fixture_adapter import FixtureTranscriptionAdapter
from app.rendering.ffmpeg_renderer import render_timeline
from app.rendering.plan_builder import build_render_plan
from app.rendering.probe import probe_media_file
from app.utils.security import compute_sha256

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_render_options_are_applied_to_ffmpeg_plan(tmp_path):
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    meta = probe_media_file(source_path)
    timeline = Timeline(
        media_id="med_render_options_test",
        original_media_hash=compute_sha256(source_path),
        source_metadata=meta,
        segments=[TimelineSegment(segment_id="s1", source_start=0.0, source_end=3.0)],
    )

    plan = build_render_plan(
        timeline, str(source_path), str(tmp_path / "out.mp4"), tmp_path,
        quality=16, preset="slow", frame_rate=60,
    )

    assert "fps=60" in plan.command[plan.command.index("-filter_complex") + 1]
    assert plan.command[plan.command.index("-crf") + 1] == "16"
    assert plan.command[plan.command.index("-preset") + 1] == "slow"
    filter_graph = plan.command[plan.command.index("-filter_complex") + 1]
    assert "[v0_norm]fps=60" in filter_graph
    assert "[[v0_norm]]" not in filter_graph


def test_crossfade_builds_overlapping_video_and_audio_filters(tmp_path):
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    meta = probe_media_file(source_path)
    timeline = Timeline(
        media_id="med_crossfade_test",
        original_media_hash=compute_sha256(source_path),
        source_metadata=meta,
        segments=[
            TimelineSegment(segment_id="a", source_start=0.0, source_end=3.0),
            TimelineSegment(
                segment_id="b", source_start=3.0, source_end=6.0,
                transition_in="crossfade", transition_duration=0.75,
            ),
        ],
    )

    plan = build_render_plan(timeline, str(source_path), str(tmp_path / "crossfade.mp4"), tmp_path)
    graph = plan.command[plan.command.index("-filter_complex") + 1]

    assert "xfade=transition=fade:duration=0.7500:offset=2.2500" in graph
    assert "acrossfade=d=0.7500" in graph


def test_crossfade_real_render_duration_and_audio_stay_synchronized(tmp_path):
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    timeline = Timeline(
        media_id="med_crossfade_render_test",
        original_media_hash=compute_sha256(source_path),
        source_metadata=probe_media_file(source_path),
        segments=[
            TimelineSegment(segment_id="a", source_start=0.0, source_end=3.0),
            TimelineSegment(
                segment_id="b", source_start=3.0, source_end=6.0,
                transition_in="crossfade", transition_duration=0.75,
            ),
        ],
    )

    manifest = render_timeline(timeline, str(source_path), output_dir=str(tmp_path))

    assert manifest.verification is not None
    assert manifest.verification.duration_within_tolerance is True
    assert abs(manifest.verification.actual_duration_s - 5.25) < 0.2
    assert manifest.verification.audio_stream_present is True


def test_29_30_31_38_render_real_fixture_and_verify_manifest(tmp_path):
    """Scenarios 29, 30, 31, 38: Real FFmpeg rendering, output duration check, AV presence, manifest."""
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    orig_hash = compute_sha256(source_path)

    meta = probe_media_file(source_path)
    seg = TimelineSegment(segment_id="s1", source_start=0.0, source_end=6.0)  # Render 6s of 12s
    timeline = Timeline(
        media_id="med_render_test",
        original_media_hash=orig_hash,
        source_metadata=meta,
        segments=[seg],
    )

    manifest = render_timeline(
        timeline=timeline,
        media_source_path=str(source_path),
        output_dir=str(tmp_path),
    )

    # 1. Output file exists and readable
    out_path = Path(manifest.output_path)
    assert out_path.is_file()
    assert manifest.file_size_bytes > 0

    # 2. Manifest verification fields
    ver = manifest.verification
    assert ver is not None
    assert ver.is_readable is True
    assert ver.duration_within_tolerance is True
    assert abs(ver.actual_duration_s - 6.0) < 0.2
    assert ver.video_stream_present is True
    assert ver.audio_stream_present is True
    assert ver.original_file_hash_verified is True
    assert ver.original_media_hash == orig_hash
    assert ver.width > 0 and ver.height > 0
    assert ver.video_codec == "h264"
    assert ver.audio_codec == "aac"

    # 3. Confirm original file was not mutated
    assert compute_sha256(source_path) == orig_hash


def test_render_burns_generated_word_anchored_subtitles(tmp_path, monkeypatch):
    """Generated transcript captions must reach the real FFmpeg ASS burn-in filter."""
    from app.config import settings

    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    transcript_data = json.loads((FIXTURES_DIR / "sample_transcript.json").read_text(encoding="utf-8"))
    timeline = Timeline(
        media_id="med_caption_burn_test",
        original_media_hash=compute_sha256(source_path),
        source_metadata=probe_media_file(source_path),
        transcript=FixtureTranscriptionAdapter(transcript_data).transcribe(str(source_path)),
        segments=[TimelineSegment(segment_id="caption_segment", source_start=0.0, source_end=6.0)],
    )
    engine = TimelineEngine(timeline)
    engine.apply_generate_captions()
    assert timeline.captions, "Subtitle generation should create transcript-anchored caption events"

    render_temp = tmp_path / "render-temp"
    monkeypatch.setattr(settings, "TEMP_DIR", str(render_temp))
    plan_dir = tmp_path / "plan-temp"
    plan = build_render_plan(
        timeline,
        str(source_path),
        str(tmp_path / "captioned.mp4"),
        plan_dir,
    )
    filter_graph = plan.command[plan.command.index("-filter_complex") + 1]
    subtitle_file = next(path for path in plan.temp_files if path.suffix == ".ass")
    subtitle_data = subtitle_file.read_text(encoding="utf-8")
    assert "[v_captioned]" in filter_graph
    assert "ass='" in filter_graph
    assert "Dialogue:" in subtitle_data and "Hello" in subtitle_data

    manifest = render_timeline(timeline, str(source_path), output_dir=str(tmp_path / "rendered"))
    assert Path(manifest.output_path).is_file()
    assert manifest.verification.is_readable is True
    assert manifest.verification.duration_within_tolerance is True


def test_32_video_without_audio(tmp_path):
    """Scenario 32: Media without audio renders correctly without audio stream."""
    source_path = FIXTURES_DIR / "sample_no_audio.mp4"
    orig_hash = compute_sha256(source_path)
    meta = probe_media_file(source_path)
    assert meta.audio_present is False

    seg = TimelineSegment(segment_id="s1", source_start=0.0, source_end=3.0, audio_enabled=False)
    timeline = Timeline(
        media_id="med_no_audio_test",
        original_media_hash=orig_hash,
        source_metadata=meta,
        segments=[seg],
    )

    manifest = render_timeline(
        timeline=timeline,
        media_source_path=str(source_path),
        output_dir=str(tmp_path),
    )

    out_meta = probe_media_file(manifest.output_path)
    assert out_meta.audio_present is False
    assert abs(out_meta.duration - 3.0) < 0.2
