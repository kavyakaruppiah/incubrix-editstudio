import math
import subprocess
from typing import List, Optional, Tuple
from app.config import settings
from app.models.transcript import TranscriptWord


class SnappingResult:
    def __init__(
        self,
        requested_time: float,
        adjusted_time: float,
        snapped: bool,
        reason: str,
    ):
        self.requested_time = round(requested_time, 4)
        self.adjusted_time = round(adjusted_time, 4)
        self.snapped = snapped
        self.reason = reason

    def to_dict(self):
        return {
            "requested_time": self.requested_time,
            "adjusted_time": self.adjusted_time,
            "snapped": self.snapped,
            "reason": self.reason,
        }


def adjust_cut_boundary(
    media_path: str,
    requested_time: float,
    source_duration: float,
    protected_words: Optional[List[TranscriptWord]] = None,
    window_ms: int = 150,
    enabled: bool = True,
    boundary_role: str = "nearest",
) -> SnappingResult:
    """
    Adjust cut boundary to nearby audio energy minimum within window_ms.
    Strictly prevents snapping outside [0, source_duration] or across protected words.
    """
    if not enabled:
        return SnappingResult(requested_time, requested_time, False, "snapping_disabled")

    if requested_time <= 0.0:
        return SnappingResult(requested_time, 0.0, False, "at_start_boundary")

    if requested_time >= source_duration:
        return SnappingResult(requested_time, source_duration, False, "at_end_boundary")

    if boundary_role not in {"nearest", "start", "end"}:
        raise ValueError("boundary_role must be nearest, start, or end")

    # A cut boundary inside a known word is moved to the outside edge of that
    # word: the edit removes the whole word instead of leaving a clipped syllable.
    search_center = requested_time
    for word in protected_words or []:
        if word.start < requested_time < word.end:
            if boundary_role == "start":
                search_center = word.start
            elif boundary_role == "end":
                search_center = word.end
            else:
                search_center = min((word.start, word.end), key=lambda edge: abs(edge - requested_time))
            break

    safe_boundary = search_center
    window_s = window_ms / 1000.0
    search_start = max(0.0, search_center - window_s)
    search_end = min(source_duration, search_center + window_s)

    # Protect against crossing words
    if protected_words:
        for w in protected_words:
            # If requested_time is outside word, boundary must not move into word
            if search_center < w.start:
                search_end = min(search_end, w.start)
            elif search_center > w.end:
                search_start = max(search_start, w.end)

    if search_start >= search_end:
        return SnappingResult(requested_time, safe_boundary, safe_boundary != requested_time, "no_valid_search_window")

    # Extract audio PCM s16le for this window
    ffmpeg_bin = settings.resolve_ffmpeg()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss", f"{search_start:.4f}",
        "-to", f"{search_end:.4f}",
        "-i", media_path,
        "-vn",
        "-f", "s16le",
        "-ac", "1",
        "-ar", "16000",
        "-v", "error",
        "pipe:1"
    ]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=4)
        raw_audio = proc.stdout
        if not raw_audio or len(raw_audio) < 320:  # less than 10ms of 16kHz 16-bit
            return SnappingResult(requested_time, safe_boundary, safe_boundary != requested_time, "no_audio_word_boundary" if safe_boundary != requested_time else "no_audio_or_empty_stream")

        # Convert raw PCM s16le to 16-bit integers
        import numpy as np
        samples = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32)
        if len(samples) == 0:
            return SnappingResult(requested_time, safe_boundary, safe_boundary != requested_time, "no_samples")

        # Sliding window of 10ms (160 samples at 16000Hz)
        frame_len = 160
        num_frames = len(samples) // frame_len
        if num_frames == 0:
            return SnappingResult(requested_time, safe_boundary, safe_boundary != requested_time, "insufficient_frames")

        rms_values = []
        for i in range(num_frames):
            frame = samples[i * frame_len : (i + 1) * frame_len]
            rms = math.sqrt(np.mean(frame ** 2))
            rms_values.append(rms)

        # Do not select an energy minimum whose frame touches a protected word.
        valid_indices = []
        for i in range(num_frames):
            center_time = search_start + (i * frame_len + frame_len / 2.0) / 16000.0
            if not any(word.start - 0.01 <= center_time <= word.end + 0.01 for word in (protected_words or [])):
                valid_indices.append(i)
        if not valid_indices:
            return SnappingResult(requested_time, safe_boundary, safe_boundary != requested_time, "no_silence_outside_protected_words")
        min_idx = min(valid_indices, key=lambda index: rms_values[index])
        min_rms = rms_values[min_idx]
        mean_rms = float(np.mean(rms_values))

        # Check if minimum is noticeably quieter than average or quiet in absolute terms
        if min_rms < 500 or (mean_rms > 0 and min_rms / mean_rms < 0.6):
            time_offset = (min_idx * frame_len + (frame_len / 2.0)) / 16000.0
            adjusted_t = search_start + time_offset
            adjusted_t = max(search_start, min(search_end, adjusted_t))
            if any(word.start - 0.01 <= adjusted_t <= word.end + 0.01 for word in (protected_words or [])):
                return SnappingResult(requested_time, safe_boundary, safe_boundary != requested_time, "word_boundary_fallback")
            return SnappingResult(requested_time, adjusted_t, True, "snapped_to_low_energy_boundary")
        else:
            return SnappingResult(requested_time, safe_boundary, safe_boundary != requested_time, "no_distinct_low_energy_minimum")

    except Exception as e:
        return SnappingResult(requested_time, safe_boundary, safe_boundary != requested_time, f"analysis_error: {str(e)}")
