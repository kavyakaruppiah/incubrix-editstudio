import os
from pathlib import Path
import pytest
from app.models.timeline import Timeline, TimelineSegment, TimelineCaption, CaptionStyle
from app.models.transcript import Transcript, TranscriptWord
from app.models.media import MediaMetadata
from app.rendering.plan_builder import generate_ass_subtitles

def test_ass_subtitle_generation_with_tamil_and_english(tmp_path):
    meta = MediaMetadata(
        duration=10.0,
        width=1920,
        height=1080,
        video_codec="h264",
        audio_present=True,
        file_size=100000,
    )
    seg = TimelineSegment(segment_id="s1", source_start=0.0, source_end=10.0, speed=1.0)
    words = [
        TranscriptWord(id="w1", text="வணக்கம்", start=1.0, end=2.0),
        TranscriptWord(id="w2", text="welcome", start=2.2, end=3.0),
        TranscriptWord(id="w3", text="நண்பர்களே", start=3.2, end=4.5),
    ]
    style = CaptionStyle(
        font_family="Nirmala UI",
        font_size=28,
        primary_color="#FFFFFF",
        outline_color="#000000",
        outline_width=2,
        bold=True,
    )
    captions = [
        TimelineCaption(
            caption_id="c1",
            text="வணக்கம் welcome நண்பர்களே",
            source_start=1.0,
            source_end=4.5,
            anchor_word_ids=["w1", "w2", "w3"],
        )
    ]
    tl = Timeline(
        media_id="test_tamil_ass",
        original_media_hash="2" * 64,
        source_metadata=meta,
        transcript=Transcript(words=words),
        segments=[seg],
        captions=captions,
        global_caption_style=style,
        caption_mode="standard",
    )

    ass_path = tmp_path / "test_tamil.ass"
    written = generate_ass_subtitles(tl, ass_path)

    assert written is True
    assert ass_path.is_file()
    with open(ass_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "[Script Info]" in content
    assert "Nirmala UI" in content
    assert "Dialogue:" in content
    assert "வணக்கம்" in content
    assert "welcome" in content
    assert "நண்பர்களே" in content

def test_ass_karaoke_highlight_generation(tmp_path):
    meta = MediaMetadata(duration=5.0, width=1280, height=720, video_codec="h264", audio_present=True, file_size=50000)
    seg = TimelineSegment(segment_id="s1", source_start=0.0, source_end=5.0, speed=1.0)
    words = [
        TranscriptWord(id="w1", text="One", start=0.5, end=1.0),
        TranscriptWord(id="w2", text="Two", start=1.1, end=1.5),
        TranscriptWord(id="w3", text="Three", start=1.6, end=2.0),
    ]
    captions = [
        TimelineCaption(
            caption_id="c1",
            text="One Two Three",
            source_start=0.5,
            source_end=2.0,
            anchor_word_ids=["w1", "w2", "w3"],
        )
    ]
    tl = Timeline(
        media_id="test_karaoke",
        original_media_hash="3" * 64,
        source_metadata=meta,
        transcript=Transcript(words=words),
        segments=[seg],
        captions=captions,
        caption_mode="karaoke",
    )

    ass_path = tmp_path / "test_karaoke.ass"
    written = generate_ass_subtitles(tl, ass_path)

    assert written is True
    assert ass_path.is_file()
    with open(ass_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check karaoke color tag {\c
    assert r"{\c" in content
    assert "One" in content
    assert "Two" in content
    assert "Three" in content


def test_sped_up_sentence_caption_keeps_minimum_readable_duration(tmp_path):
    meta = MediaMetadata(duration=5.0, width=1280, height=720, video_codec="h264", audio_present=True, file_size=1000)
    timeline = Timeline(
        media_id="fast_caption", original_media_hash="4" * 64,
        source_metadata=meta,
        transcript=Transcript(words=[TranscriptWord(id="w1", text="Hello", start=1.0, end=1.4)]),
        segments=[TimelineSegment(segment_id="s1", source_start=0, source_end=5, speed=2.0)],
        captions=[TimelineCaption(caption_id="c1", text="Hello", anchor_word_ids=["w1"])],
    )

    ass_path = tmp_path / "fast_caption.ass"
    assert generate_ass_subtitles(timeline, ass_path)
    dialogue = next(line for line in ass_path.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:"))
    _, start, end, *_ = dialogue.split(",", 4)

    def to_seconds(value):
        hours, minutes, seconds = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    assert to_seconds(end) - to_seconds(start) >= 0.69
