import pytest
from app.models.media import MediaMetadata
from app.models.timeline import Timeline, TimelineSegment
from app.models.transcript import Transcript, TranscriptWord
from app.services.smart_suggestions import SmartSuggestionsService

@pytest.fixture
def timeline_with_anomalies():
    meta = MediaMetadata(
        duration=30.0,
        width=1280,
        height=720,
        video_codec="h264",
        audio_present=True,
        file_size=500000,
    )
    seg = TimelineSegment(segment_id="s1", source_start=0.0, source_end=30.0, speed=1.0)
    words = [
        TranscriptWord(id="w1", text="Hello", start=1.0, end=1.5),
        TranscriptWord(id="w2", text="um", start=1.6, end=1.9),
        TranscriptWord(id="w3", text="welcome", start=2.0, end=2.5),
        # Long pause between 2.5 and 5.0 (2.5s > 1.0s)
        TranscriptWord(id="w4", text="to", start=5.0, end=5.2),
        TranscriptWord(id="w5", text="the", start=5.3, end=5.5),
        TranscriptWord(id="w6", text="the", start=5.6, end=5.8),  # Repeated word
        TranscriptWord(id="w7", text="pricing", start=5.9, end=6.5),
        TranscriptWord(id="w8", text="plan", start=6.6, end=7.0),
    ]
    return Timeline(
        media_id="test_sugg",
        original_media_hash="1" * 64,
        source_metadata=meta,
        transcript=Transcript(words=words),
        segments=[seg],
        revision=1,
    )

def test_detect_long_pauses(timeline_with_anomalies):
    service = SmartSuggestionsService()
    suggestions = service.generate_suggestions(timeline_with_anomalies)

    pause_suggs = [s for s in suggestions if s.type == "long_pause"]
    assert len(pause_suggs) >= 1
    assert "2.5s" in pause_suggs[0].description or "pause" in pause_suggs[0].description
    assert pause_suggs[0].suggested_action == "remove all long pauses"

def test_detect_filler_words(timeline_with_anomalies):
    service = SmartSuggestionsService()
    suggestions = service.generate_suggestions(timeline_with_anomalies)

    filler_suggs = [s for s in suggestions if s.type == "filler_words"]
    assert len(filler_suggs) >= 1
    assert "um" in filler_suggs[0].description
    assert filler_suggs[0].suggested_action == "remove filler words"

def test_detect_repeated_words(timeline_with_anomalies):
    service = SmartSuggestionsService()
    suggestions = service.generate_suggestions(timeline_with_anomalies)

    repeat_suggs = [s for s in suggestions if s.type == "repeated_words"]
    assert len(repeat_suggs) >= 1
    assert "the" in repeat_suggs[0].description

def test_topic_search_suggestions(timeline_with_anomalies):
    service = SmartSuggestionsService()
    suggestions = service.generate_suggestions(timeline_with_anomalies, topic="pricing")

    topic_suggs = [s for s in suggestions if s.type == "topic_match"]
    assert len(topic_suggs) >= 1
    assert "pricing" in topic_suggs[0].description.lower()
