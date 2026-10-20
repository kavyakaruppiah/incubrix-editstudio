import math
import re
from typing import List, Optional, Tuple
from app.models.transcript import Transcript, TranscriptWord, normalize_text


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds into SRT timestamp: HH:MM:SS,mmm"""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    """Format seconds into WebVTT timestamp: HH:MM:SS.mmm"""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def parse_timestamp_str(ts_str: str) -> float:
    """Parse SRT or VTT timestamp HH:MM:SS[,.]mmm into seconds float."""
    ts_str = ts_str.strip().replace(",", ".")
    parts = ts_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return float(h) * 3600.0 + float(m) * 60.0 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return float(m) * 60.0 + float(s)
    return float(ts_str)


def group_words_into_sentences(words: List[TranscriptWord], max_words_per_cue: int = 8, max_gap_s: float = 1.2) -> List[List[TranscriptWord]]:
    """Group word list into natural subtitle phrases/cues based on punctuation, speaker changes, or time gaps."""
    if not words:
        return []

    cues: List[List[TranscriptWord]] = []
    current_cue: List[TranscriptWord] = []

    for idx, w in enumerate(words):
        if not current_cue:
            current_cue.append(w)
            continue

        prev_w = current_cue[-1]
        speaker_changed = (w.speaker is not None and prev_w.speaker is not None and w.speaker != prev_w.speaker)
        time_gap = (w.start - prev_w.end) > max_gap_s
        ends_sentence = prev_w.text.rstrip().endswith((".", "!", "?", "...", "।", ";"))
        cue_full = len(current_cue) >= max_words_per_cue

        if speaker_changed or time_gap or ends_sentence or cue_full:
            cues.append(current_cue)
            current_cue = [w]
        else:
            current_cue.append(w)

    if current_cue:
        cues.append(current_cue)

    return cues


def transcript_to_txt(transcript: Transcript) -> str:
    """Export transcript as clean plaintext."""
    if not transcript.words:
        return ""
    lines: List[str] = []
    current_speaker = None
    line_words: List[str] = []

    for w in transcript.words:
        if w.speaker and w.speaker != current_speaker:
            if line_words:
                prefix = f"[{current_speaker}] " if current_speaker else ""
                lines.append(prefix + " ".join(line_words))
                line_words = []
            current_speaker = w.speaker
        line_words.append(w.text)

    if line_words:
        prefix = f"[{current_speaker}] " if current_speaker else ""
        lines.append(prefix + " ".join(line_words))

    return "\n".join(lines)


# Alias for compatibility
transcript_to_plain_text = transcript_to_txt


def transcript_to_srt(transcript: Transcript) -> str:
    """Export transcript to standard SubRip (.srt) subtitle format."""
    cues = group_words_into_sentences(transcript.words)
    output_lines: List[str] = []

    for idx, cue in enumerate(cues, start=1):
        start_ts = format_srt_timestamp(cue[0].start)
        end_ts = format_srt_timestamp(cue[-1].end)
        speaker_prefix = f"[{cue[0].speaker}] " if cue[0].speaker else ""
        text = speaker_prefix + " ".join(w.text for w in cue)
        output_lines.append(f"{idx}\n{start_ts} --> {end_ts}\n{text}\n")

    return "\n".join(output_lines)


def transcript_to_vtt(transcript: Transcript) -> str:
    """Export transcript to standard WebVTT (.vtt) subtitle format."""
    cues = group_words_into_sentences(transcript.words)
    output_lines: List[str] = ["WEBVTT\n"]

    for idx, cue in enumerate(cues, start=1):
        start_ts = format_vtt_timestamp(cue[0].start)
        end_ts = format_vtt_timestamp(cue[-1].end)
        speaker_prefix = f"<v {cue[0].speaker}>" if cue[0].speaker else ""
        suffix = "</v>" if cue[0].speaker else ""
        text = f"{speaker_prefix}{' '.join(w.text for w in cue)}{suffix}"
        output_lines.append(f"{idx}\n{start_ts} --> {end_ts}\n{text}\n")

    return "\n".join(output_lines)


def parse_srt_or_vtt_to_transcript(content: str, provenance: str = "imported_subtitles") -> Transcript:
    """
    Parse SRT or WebVTT string content into structured Transcript with word-level timestamps.
    Automatically handles timestamps, multi-line cues, speaker labels (<v Speaker>, [Speaker]:),
    and distributes words evenly across cue intervals.
    """
    lines = [line.strip() for line in content.strip().splitlines()]
    if not lines:
        return Transcript(words=[])

    # Strip WEBVTT header if present
    if lines and lines[0].upper().startswith("WEBVTT"):
        lines = lines[1:]

    # Match timing line: e.g. 00:00:01,000 --> 00:00:04,500
    timing_regex = re.compile(r"(?P<start>[\d:,\.]+)\s+-->\s+(?P<end>[\d:,\.]+)")

    cues: List[Tuple[float, float, Optional[str], str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue

        match = timing_regex.search(line)
        if not match:
            # Could be a numeric counter line (e.g. "1"), check next line
            if i + 1 < len(lines) and timing_regex.search(lines[i + 1]):
                i += 1
                match = timing_regex.search(lines[i])
            else:
                i += 1
                continue

        if match:
            start_s = parse_timestamp_str(match.group("start"))
            end_s = parse_timestamp_str(match.group("end"))
            i += 1

            text_lines: List[str] = []
            while i < len(lines) and lines[i] and not timing_regex.search(lines[i]):
                # If it's a numeric index line preceding next timing, break
                if lines[i].isdigit() and i + 1 < len(lines) and timing_regex.search(lines[i + 1]):
                    break
                text_lines.append(lines[i])
                i += 1

            raw_text = " ".join(text_lines).strip()
            if not raw_text:
                continue

            # Check for speaker tag e.g. <v Speaker A>Text</v> or [Speaker A]: Text
            speaker = None
            vtt_speaker_match = re.match(r"<v\s+([^>]+)>(.*)(?:</v>)?", raw_text, re.IGNORECASE)
            if vtt_speaker_match:
                speaker = vtt_speaker_match.group(1).strip()
                raw_text = vtt_speaker_match.group(2).strip()
            else:
                srt_speaker_match = re.match(r"\[([^\]]+)\]:\s*(.*)", raw_text) or re.match(r"\[([^\]]+)\]\s+(.*)", raw_text)
                if srt_speaker_match:
                    speaker = srt_speaker_match.group(1).strip()
                    raw_text = srt_speaker_match.group(2).strip()

            cues.append((start_s, end_s, speaker, raw_text))

    # Convert cues into word-level timestamps
    words: List[TranscriptWord] = []
    word_counter = 1

    for start_s, end_s, speaker, cue_text in cues:
        tokens = [t for t in cue_text.split() if t.strip()]
        if not tokens:
            continue

        cue_dur = max(0.1, end_s - start_s)
        word_dur = cue_dur / len(tokens)

        for idx, token in enumerate(tokens):
            w_start = round(start_s + idx * word_dur, 3)
            w_end = round(min(end_s, w_start + word_dur * 0.95), 3)
            if w_end <= w_start:
                w_end = round(w_start + 0.05, 3)

            words.append(
                TranscriptWord(
                    id=f"w_{word_counter:04d}",
                    text=token,
                    normalized_text=normalize_text(token),
                    start=w_start,
                    end=w_end,
                    speaker=speaker,
                    confidence=1.0,
                    provenance=provenance,
                    warnings=[],
                )
            )
            word_counter += 1

    return Transcript(words=words)


def parse_srt_to_words(content: str) -> List[TranscriptWord]:
    return parse_srt_or_vtt_to_transcript(content).words


def parse_vtt_to_words(content: str) -> List[TranscriptWord]:
    return parse_srt_or_vtt_to_transcript(content).words


