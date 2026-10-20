from pathlib import Path
import pytest
from app.models.timeline import BackgroundMusic, Timeline, TimelineSegment, CaptionStyle, VideoEffectsContainer
from app.rendering.plan_builder import build_render_plan
from app.models.transcript import Transcript, TranscriptWord
from app.rendering.ffmpeg_renderer import render_timeline
from app.rendering.probe import probe_media_file
from app.utils.security import compute_sha256

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

def test_render_with_cinematic_color_and_vertical_aspect(tmp_path):
    """Integration test: Real FFmpeg render with cinematic color grade and 9:16 vertical crop."""
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    orig_hash = compute_sha256(source_path)
    meta = probe_media_file(source_path)

    # 4-second segment
    seg = TimelineSegment(segment_id="s1", source_start=1.0, source_end=5.0)
    words = [
        TranscriptWord(id="w1", text="Cinematic", start=1.5, end=2.5),
        TranscriptWord(id="w2", text="Reel", start=3.0, end=4.0),
    ]

    effects = VideoEffectsContainer(
        color_grade="cinematic",
        transitions=["fade_in_out"],
        audio_ducking=True,
        audio_normalize=True,
    )

    timeline = Timeline(
        media_id="adv_render_test",
        original_media_hash=orig_hash,
        source_metadata=meta,
        segments=[seg],
        transcript=Transcript(words=words),
        effects=effects,
        aspect_ratio="9:16",
        caption_mode="standard",
    )

    manifest = render_timeline(
        timeline=timeline,
        media_source_path=str(source_path),
        output_dir=str(tmp_path),
    )

    out_path = Path(manifest.output_path)
    assert out_path.is_file()
    assert manifest.file_size_bytes > 0

    # Inspect rendered output with FFprobe
    out_meta = probe_media_file(manifest.output_path)
    assert out_meta.video_codec is not None
    assert out_meta.audio_present is True
    # Verify vertical aspect: height > width
    assert out_meta.height > out_meta.width
    # Verify duration within tolerance (4.0s)
    assert abs(out_meta.duration - 4.0) < 0.25

    # Check manifest verification
    ver = manifest.verification
    assert ver.is_readable is True
    assert ver.duration_within_tolerance is True
    assert ver.video_stream_present is True
    assert ver.audio_stream_present is True


def test_render_with_social_portrait_4_5_aspect(tmp_path):
    """The 4:5 quick canvas option produces a real 1080x1350 MP4 render."""
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    meta = probe_media_file(source_path)
    timeline = Timeline(
        media_id="portrait_4_5_render_test",
        original_media_hash=compute_sha256(source_path),
        source_metadata=meta,
        segments=[TimelineSegment(segment_id="s1", source_start=0.0, source_end=3.0)],
        aspect_ratio="4:5",
    )

    manifest = render_timeline(
        timeline=timeline,
        media_source_path=str(source_path),
        output_dir=str(tmp_path),
    )

    rendered = probe_media_file(manifest.output_path)
    assert rendered.width == 1080
    assert rendered.height == 1350
    assert rendered.audio_present
    assert manifest.verification.is_readable
    assert manifest.verification.duration_within_tolerance

def test_render_with_tamil_karaoke_subtitles(tmp_path):
    """Integration test: Real FFmpeg render burning Tamil & English karaoke subtitles."""
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    orig_hash = compute_sha256(source_path)
    meta = probe_media_file(source_path)

    seg = TimelineSegment(segment_id="s1", source_start=0.0, source_end=4.0)
    words = [
        TranscriptWord(id="w1", text="வணக்கம்", start=0.5, end=1.5),
        TranscriptWord(id="w2", text="India", start=1.8, end=2.8),
    ]

    style = CaptionStyle(
        font_family="Nirmala UI",
        font_size=26,
        primary_color="#FFFFFF",
        outline_color="#000000",
        outline_width=2,
    )

    timeline = Timeline(
        media_id="tamil_sub_render_test",
        original_media_hash=orig_hash,
        source_metadata=meta,
        segments=[seg],
        transcript=Transcript(words=words),
        caption_style=style,
        caption_mode="karaoke",
    )

    manifest = render_timeline(
        timeline=timeline,
        media_source_path=str(source_path),
        output_dir=str(tmp_path),
    )

    out_path = Path(manifest.output_path)
    assert out_path.is_file()
    assert manifest.file_size_bytes > 0

    out_meta = probe_media_file(manifest.output_path)
    assert out_meta.video_codec is not None
    assert abs(out_meta.duration - 4.0) < 0.25


def test_background_music_ducks_under_source_speech(tmp_path):
    """Ducking must be present in and executable by the real FFmpeg render graph."""
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    music_path = FIXTURES_DIR / "ambient_bgm.mp3"
    meta = probe_media_file(source_path)
    timeline = Timeline(
        media_id="bgm_ducking_test",
        original_media_hash=compute_sha256(source_path),
        source_metadata=meta,
        segments=[TimelineSegment(segment_id="s1", source_start=0.0, source_end=4.0)],
        background_music=BackgroundMusic(
            track_id="test_music",
            track_path=str(music_path),
            volume=0.3,
            ducking_enabled=True,
            ducking_attenuation_db=12.0,
            speech_threshold=0.03,
        ),
    )

    plan = build_render_plan(timeline, str(source_path), str(tmp_path / "ducked.mp4"), tmp_path)
    graph = plan.command[plan.command.index("-filter_complex") + 1]
    assert "sidechaincompress=threshold=0.0300" in graph
    assert "a_bgm_ducked" in graph

    manifest = render_timeline(timeline, str(source_path), str(tmp_path))
    output = probe_media_file(manifest.output_path)
    assert output.audio_present is True
    assert abs(output.duration - 4.0) < 0.25


def test_render_applies_audio_noise_reduction_filter(tmp_path):
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    meta = probe_media_file(source_path)
    timeline = Timeline(
        media_id="audio_denoise_test",
        original_media_hash=compute_sha256(source_path),
        source_metadata=meta,
        segments=[TimelineSegment(segment_id="s1", source_start=0.0, source_end=4.0)],
    )
    timeline.audio_effects.noise_reduction_db = 12.0

    manifest = render_timeline(timeline, str(source_path), str(tmp_path))

    output = probe_media_file(manifest.output_path)
    assert output.audio_present is True
    assert abs(output.duration - 4.0) < 0.25


@pytest.mark.parametrize("rotation, filters", [(90, "transpose=clock"), (270, "transpose=cclock"), (180, "hflip,vflip")])
def test_render_applies_video_rotation(tmp_path, rotation, filters):
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    meta = probe_media_file(source_path)
    timeline = Timeline(
        media_id=f"rotate_{rotation}_test",
        original_media_hash=compute_sha256(source_path),
        source_metadata=meta,
        segments=[TimelineSegment(segment_id="s1", source_start=0.0, source_end=4.0)],
    )
    timeline.video_effects.rotation_degrees = rotation
    plan = build_render_plan(timeline, str(source_path), str(tmp_path / f"rotate_{rotation}.mp4"), tmp_path)
    graph = plan.command[plan.command.index("-filter_complex") + 1]
    assert filters in graph

    manifest = render_timeline(timeline, str(source_path), str(tmp_path))
    output = probe_media_file(manifest.output_path)
    assert output.audio_present is True
    if rotation in {90, 270}:
        assert output.width == meta.height
        assert output.height == meta.width


def test_render_applies_horizontal_video_mirror(tmp_path):
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    meta = probe_media_file(source_path)
    timeline = Timeline(
        media_id="horizontal_mirror_test",
        original_media_hash=compute_sha256(source_path),
        source_metadata=meta,
        segments=[TimelineSegment(segment_id="s1", source_start=0.0, source_end=4.0)],
    )
    timeline.video_effects.horizontal_flip = True

    manifest = render_timeline(timeline, str(source_path), str(tmp_path))

    output = probe_media_file(manifest.output_path)
    assert output.audio_present is True
    assert output.width == meta.width
    assert output.height == meta.height


def test_render_applies_segment_speed_change(tmp_path):
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    meta = probe_media_file(source_path)
    timeline = Timeline(
        media_id="speed_change_render_test",
        original_media_hash=compute_sha256(source_path),
        source_metadata=meta,
        segments=[TimelineSegment(segment_id="s1", source_start=0.0, source_end=4.0, speed=1.5)],
    )

    manifest = render_timeline(timeline, str(source_path), str(tmp_path))

    output = probe_media_file(manifest.output_path)
    assert abs(output.duration - (4.0 / 1.5)) < 0.25
