import difflib
import re
import uuid
from typing import List, Optional, Tuple
from app.models.transcript import Transcript, TranscriptWord, normalize_text


class ScriptAligner:
    """
    Aligns external voice-over script text (from PDF, Word, etc.)
    with the video audio's word-level timestamps.
    """

    def align_script_to_audio(
        self,
        script_text: str,
        audio_words: List[TranscriptWord],
        media_duration: float,
    ) -> Transcript:
        """
        Produce a word-level Transcript using the clean wording from the script
        and the precise timestamps from the video audio.
        """
        # Tokenize script text preserving original tokens (with punctuation)
        raw_tokens = self._tokenize_script(script_text)
        if not raw_tokens:
            raise ValueError("No words found in voice-over script content.")

        if not audio_words:
            # Fallback: distribute script words across video duration at natural pacing
            return self._distribute_words_across_duration(raw_tokens, media_duration)

        # Normalized tokens for sequence alignment
        norm_audio = [w.normalized_text for w in audio_words]
        norm_script = [normalize_text(t) for t in raw_tokens]

        # Use SequenceMatcher to find optimal matching blocks
        matcher = difflib.SequenceMatcher(None, norm_audio, norm_script)
        matching_blocks = matcher.get_matching_blocks()

        # Array to store aligned timings: index -> (start, end, confidence, speaker)
        aligned_timings: List[Optional[Tuple[float, float, float, Optional[str]]]] = [None] * len(raw_tokens)

        for a_idx, s_idx, size in matching_blocks:
            for k in range(size):
                aw = audio_words[a_idx + k]
                aligned_timings[s_idx + k] = (
                    aw.start,
                    aw.end,
                    aw.confidence or 0.95,
                    aw.speaker,
                )

        # Interpolate timings for unaligned words
        final_words: List[TranscriptWord] = []
        for i, token in enumerate(raw_tokens):
            if aligned_timings[i] is not None:
                start, end, conf, spk = aligned_timings[i]
            else:
                start, end = self._interpolate_timing(i, aligned_timings, media_duration)
                conf = 0.70
                spk = None

            final_words.append(
                TranscriptWord(
                    id=f"w_{i + 1:04d}",
                    text=token,
                    normalized_text=normalize_text(token),
                    start=round(max(0.0, min(media_duration, start)), 3),
                    end=round(max(0.01, min(media_duration, end)), 3),
                    speaker=spk,
                    confidence=conf,
                    provenance="voiceover_aligned",
                )
            )

        # Validate monotonic timestamps
        self._ensure_monotonic(final_words, media_duration)

        return Transcript(words=final_words)

    def _tokenize_script(self, text: str) -> List[str]:
        # Split on whitespace but preserve words
        tokens = text.split()
        return [t.strip() for t in tokens if t.strip()]

    def _interpolate_timing(
        self,
        target_idx: int,
        timings: List[Optional[Tuple[float, float, float, Optional[str]]]],
        media_duration: float,
    ) -> Tuple[float, float]:
        """Interpolate timestamps for a word that was not directly matched in audio."""
        prev_idx = None
        for j in range(target_idx - 1, -1, -1):
            if timings[j] is not None:
                prev_idx = j
                break

        next_idx = None
        for j in range(target_idx + 1, len(timings)):
            if timings[j] is not None:
                next_idx = j
                break

        prev_time = timings[prev_idx][1] if prev_idx is not None else 0.0
        next_time = timings[next_idx][0] if next_idx is not None else media_duration

        if next_time < prev_time:
            next_time = prev_time + 0.35

        gap_count = (next_idx if next_idx is not None else len(timings)) - (prev_idx if prev_idx is not None else -1)
        sub_idx = target_idx - (prev_idx if prev_idx is not None else -1)

        available_gap = max(0.2 * gap_count, next_time - prev_time)
        step = available_gap / max(1, gap_count)

        start = prev_time + (sub_idx - 1) * step
        end = start + min(0.35, step * 0.9)

        return (start, end)

    def _distribute_words_across_duration(
        self,
        tokens: List[str],
        duration: float,
    ) -> Transcript:
        """Evenly space words when no reference audio words are available."""
        n = len(tokens)
        pace = min(0.4, max(0.15, duration / max(1, n)))
        words = []
        for i, token in enumerate(tokens):
            start = round(i * pace, 3)
            end = round(start + pace * 0.85, 3)
            if start >= duration:
                start = max(0.0, duration - 0.2)
                end = duration
            words.append(
                TranscriptWord(
                    id=f"w_{i + 1:04d}",
                    text=token,
                    normalized_text=normalize_text(token),
                    start=start,
                    end=end,
                    speaker=None,
                    confidence=0.85,
                    provenance="voiceover_script_distributed",
                )
            )
        return Transcript(words=words)

    def _ensure_monotonic(self, words: List[TranscriptWord], max_dur: float) -> None:
        """Ensure all word start/end times are valid and strictly ascending."""
        for i in range(len(words)):
            w = words[i]
            if w.end <= w.start:
                w.end = round(w.start + 0.2, 3)
            if i > 0 and w.start < words[i - 1].start:
                w.start = words[i - 1].end
                w.end = max(w.start + 0.15, w.end)
            if w.end > max_dur:
                w.end = max_dur
                if w.start >= w.end:
                    w.start = max(0.0, w.end - 0.1)


script_aligner = ScriptAligner()
