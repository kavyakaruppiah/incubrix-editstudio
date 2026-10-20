import pytest
from app.models.transcript import Transcript, TranscriptWord

def test_transcript_edit_word():
    words = [
        TranscriptWord(id="w1", text="helko", start=1.0, end=1.5, confidence=0.4),
        TranscriptWord(id="w2", text="world", start=1.6, end=2.0, confidence=0.95),
    ]
    t = Transcript(words=words)

    # Edit word w1
    updated = t.edit_word("w1", new_text="hello", new_start=0.9, new_speaker="Host")
    assert updated is not None
    assert updated.text == "hello"
    assert updated.start == 0.9
    assert updated.speaker == "Host"
    assert updated.confidence == 1.0  # Manually corrected words get confidence 1.0

    # Non-existent word
    assert t.edit_word("w999", new_text="test") is None

def test_transcript_delete_word():
    words = [
        TranscriptWord(id="w1", text="um", start=1.0, end=1.2),
        TranscriptWord(id="w2", text="actually", start=1.3, end=1.8),
    ]
    t = Transcript(words=words)

    # Delete w1
    assert t.delete_word("w1") is True
    assert len(t.words) == 1
    assert t.words[0].id == "w2"

    # Delete missing
    assert t.delete_word("w999") is False

def test_transcript_search():
    words = [
        TranscriptWord(id="w1", text="Artificial", start=1.0, end=1.5),
        TranscriptWord(id="w2", text="Intelligence", start=1.6, end=2.2),
        TranscriptWord(id="w3", text="and", start=2.3, end=2.5),
        TranscriptWord(id="w4", text="Machine", start=2.6, end=3.0),
        TranscriptWord(id="w5", text="Learning", start=3.1, end=3.6),
    ]
    t = Transcript(words=words)

    results = t.search_words("intel")
    assert len(results) == 1
    assert results[0].text == "Intelligence"

    # Multi-match search
    results2 = t.search_words("in")
    # 'Artificial' (contains in? Art-i-fic-ial: no, wait: i-n? No, art-i-fi-c-i-a-l has no in. Intelligence has in. Machine has in. Learning has in.)
    matching_ids = [w.id for w in results2]
    assert "w2" in matching_ids

def test_transcript_flagged_words():
    words = [
        TranscriptWord(id="w1", text="clear", start=1.0, end=1.5, confidence=0.98),
        TranscriptWord(id="w2", text="mumble", start=1.6, end=2.0, confidence=0.45),
        TranscriptWord(id="w3", text="whisper", start=2.1, end=2.5, confidence=0.55),
        TranscriptWord(id="w4", text="loud", start=2.6, end=3.0, confidence=0.85),
    ]
    t = Transcript(words=words)

    flagged = t.flagged_words(threshold=0.6)
    assert len(flagged) == 2
    assert [w.id for w in flagged] == ["w2", "w3"]
