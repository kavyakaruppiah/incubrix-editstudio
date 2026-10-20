import re
import string
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator


def normalize_text(text: str) -> str:
    """Lowercase, strip leading/trailing punctuation and whitespace for robust matching."""
    text = text.lower().strip()
    # Strip leading/trailing punctuation but preserve inner apostrophes (e.g., don't -> don't)
    text = text.strip(string.punctuation + "“”‘’")
    return text


class TranscriptWord(BaseModel):
    id: str = Field(..., description="Stable persistent word identifier, e.g. w_0001")
    text: str = Field(..., description="Original raw word text")
    normalized_text: str = Field(default="", description="Normalized text for deterministic matching")
    start: float = Field(..., ge=0, description="Source start time in seconds")
    end: float = Field(..., ge=0, description="Source end time in seconds")
    speaker: Optional[str] = Field(default=None, description="Speaker identifier or null")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Confidence score 0.0 to 1.0")
    provenance: str = Field(default="user_or_adapter", description="Source or adapter that generated the word")
    warnings: List[str] = Field(default_factory=list, description="Warnings associated with this word")

    @model_validator(mode="after")
    def validate_word(self) -> "TranscriptWord":
        if not self.normalized_text:
            self.normalized_text = normalize_text(self.text)
        if self.start > self.end:
            raise ValueError(f"Invalid word interval: start ({self.start}) > end ({self.end}) for word '{self.text}' ({self.id})")
        return self


class Transcript(BaseModel):
    words: List[TranscriptWord] = Field(default_factory=list)
    language: Optional[str] = Field(default="en", description="Detected or specified language code, e.g. en, ta")
    language_probability: Optional[float] = Field(default=None, description="Confidence of language detection")

    def validate_against_source(self, source_duration: float) -> List[str]:
        """Validate transcript consistency against source duration. Returns list of validation warnings."""
        warnings: List[str] = []
        prev_end = 0.0
        seen_ids = set()

        for idx, word in enumerate(self.words):
            if word.id in seen_ids:
                raise ValueError(f"Duplicate word id detected: {word.id}")
            seen_ids.add(word.id)

            if word.start > source_duration + 0.05:
                raise ValueError(f"Word '{word.text}' ({word.id}) starts at {word.start}s, exceeding media duration {source_duration}s")
            if word.end > source_duration + 0.05:
                warnings.append(f"Word '{word.text}' ({word.id}) end {word.end}s slightly exceeds duration {source_duration}s")

            if word.start < prev_end - 0.01:
                warnings.append(f"Word '{word.text}' ({word.id}) overlaps with previous word ending at {prev_end:.2f}s")
            prev_end = max(prev_end, word.end)

        return warnings

    def get_word_by_id(self, word_id: str) -> Optional[TranscriptWord]:
        for w in self.words:
            if w.id == word_id:
                return w
        return None

    def edit_word(
        self,
        word_id: str,
        new_text: Optional[str] = None,
        new_start: Optional[float] = None,
        new_end: Optional[float] = None,
        new_speaker: Optional[str] = None,
    ) -> Optional[TranscriptWord]:
        """Edit word text, timestamps, or speaker assignment."""
        w = self.get_word_by_id(word_id)
        if not w:
            return None
        if new_text is not None:
            w.text = new_text.strip()
            w.normalized_text = normalize_text(w.text)
        if new_start is not None:
            w.start = round(new_start, 3)
        if new_end is not None:
            w.end = round(new_end, 3)
        if new_speaker is not None:
            w.speaker = new_speaker.strip() if new_speaker else None
        w.confidence = 1.0
        w.provenance = "user_edit"
        return w

    def delete_word(self, word_id: str) -> bool:
        """Delete a word by ID."""
        for idx, w in enumerate(self.words):
            if w.id == word_id:
                self.words.pop(idx)
                return True
        return False

    def search_words(self, query: str) -> List[TranscriptWord]:
        """Search words by text or normalized text substring."""
        clean_q = normalize_text(query)
        return [w for w in self.words if clean_q in w.normalized_text or clean_q in w.text.lower()]

    def flagged_words(self, threshold: float = 0.5) -> List[TranscriptWord]:
        """Return words with low confidence or explicit warnings."""
        return [
            w for w in self.words
            if (w.confidence is not None and w.confidence < threshold) or bool(w.warnings)
        ]

    def to_txt(self) -> str:
        from app.transcription.srt_vtt import transcript_to_txt
        return transcript_to_txt(self)

    def to_srt(self) -> str:
        from app.transcription.srt_vtt import transcript_to_srt
        return transcript_to_srt(self)

    def to_vtt(self) -> str:
        from app.transcription.srt_vtt import transcript_to_vtt
        return transcript_to_vtt(self)

    def find_phrase_occurrences(self, phrase: str, speaker: Optional[str] = None) -> List[List[TranscriptWord]]:
        """
        Find occurrences of a contiguous sequence of normalized words matching phrase.
        If speaker is specified, only matches spoken by that speaker.
        """
        phrase_tokens = [normalize_text(token) for token in phrase.split() if normalize_text(token)]
        if not phrase_tokens:
            return []

        results: List[List[TranscriptWord]] = []
        n = len(phrase_tokens)

        for i in range(len(self.words) - n + 1):
            window = self.words[i : i + n]
            if speaker is not None and any(w.speaker != speaker for w in window):
                continue
            window_tokens = [w.normalized_text for w in window]
            if window_tokens == phrase_tokens:
                results.append(window)

        return results

