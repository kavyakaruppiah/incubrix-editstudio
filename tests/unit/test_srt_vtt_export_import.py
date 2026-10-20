import pytest
from app.models.transcript import Transcript, TranscriptWord
from app.transcription.srt_vtt import (
    transcript_to_srt,
    transcript_to_vtt,
    transcript_to_plain_text,
    parse_srt_to_words,
    parse_vtt_to_words,
)

def test_transcript_to_srt_export():
    words = [
        TranscriptWord(id="w1", text="Hello", start=0.5, end=1.0, speaker="Speaker 1"),
        TranscriptWord(id="w2", text="world!", start=1.1, end=1.8, speaker="Speaker 1"),
        TranscriptWord(id="w3", text="Welcome", start=3.0, end=3.5, speaker="Speaker 2"),
    ]
    t = Transcript(words=words)
    srt_content = transcript_to_srt(t)

    assert "1" in srt_content
    assert "00:00:00,500 --> 00:00:01,800" in srt_content
    assert "Hello world!" in srt_content
    assert "00:00:03,000 --> 00:00:03,500" in srt_content
    assert "Welcome" in srt_content

def test_transcript_to_vtt_export():
    words = [
        TranscriptWord(id="w1", text="வணக்கம்", start=0.0, end=1.2),
        TranscriptWord(id="w2", text="நண்பர்களே", start=1.3, end=2.0),
    ]
    t = Transcript(words=words)
    vtt_content = transcript_to_vtt(t)

    assert vtt_content.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:02.000" in vtt_content
    assert "வணக்கம் நண்பர்களே" in vtt_content

def test_transcript_to_plain_text():
    words = [
        TranscriptWord(id="w1", text="Good", start=0.0, end=0.4),
        TranscriptWord(id="w2", text="morning", start=0.5, end=0.9),
    ]
    t = Transcript(words=words)
    plain = transcript_to_plain_text(t)
    assert plain == "Good morning"

def test_parse_srt_roundtrip():
    sample_srt = """1
00:00:01,000 --> 00:00:02,500
Testing subtitle import

2
00:00:03,200 --> 00:00:04,800
Second subtitle block
"""
    words = parse_srt_to_words(sample_srt)
    assert len(words) == 6
    assert words[0].text == "Testing"
    assert words[0].start == 1.0
    assert words[2].text == "import"
    assert words[3].text == "Second"
    assert words[3].start == 3.2

def test_parse_vtt_import():
    sample_vtt = """WEBVTT

00:00:00.500 --> 00:00:02.000
Quick brown fox

00:00:02.500 --> 00:00:03.500
Jumps over
"""
    words = parse_vtt_to_words(sample_vtt)
    assert len(words) == 5
    assert words[0].text == "Quick"
    assert words[0].start == 0.5
    assert words[2].text == "fox"
    assert words[3].text == "Jumps"
