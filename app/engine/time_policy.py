from typing import List, Optional, Tuple
from app.models.timeline import TimelineSegment
from app.models.transcript import Transcript, TranscriptWord


def time_policy_statement(time_basis: str) -> str:
    """Human-readable policy tag for responses that resolved an explicit time."""
    if time_basis in {"source", "original", "original_source"}:
        return "Time policy: original source timeline."
    return "Time policy: current timeline (before this edit)."


def requested_time_basis(instruction: str) -> Optional[str]:
    """Infer the user-facing clock policy for a prompt containing a time."""
    import re

    has_time = re.search(
        r"\d|\b(?:hours?|hrs?|minutes?|mins?|seconds?|secs?|a\s+minute|one\s+minute)\b",
        instruction,
        re.IGNORECASE,
    )
    if not has_time:
        return None
    if re.search(r"\b(?:original|source)\b", instruction, re.IGNORECASE):
        return "source"
    return "current_timeline"


def compute_segment_output_offsets(segments: List[TimelineSegment]) -> List[Tuple[float, float]]:
    """
    Compute [output_start, output_end] for each segment in ordered list.
    output_start_0 = 0.0
    output_end_i = output_start_i + (source_end - source_start) / speed
    Incoming transitions overlap adjacent segments and reduce the current timeline offset.
    """
    offsets: List[Tuple[float, float]] = []
    curr = 0.0
    for index, seg in enumerate(segments):
        if index:
            curr -= seg.transition_duration
        dur = seg.output_duration
        offsets.append((curr, curr + dur))
        curr += dur
    return offsets


def source_time_to_output_times(segments: List[TimelineSegment], source_t: float) -> List[float]:
    """
    Map a source time to all corresponding output times.
    If the source time is cut, returns empty list.
    If present in multiple segments (reordering/duplication), returns multiple output times.
    """
    offsets = compute_segment_output_offsets(segments)
    results: List[float] = []

    for i, seg in enumerate(segments):
        # Check if source_t falls within this segment
        # Allow small epsilon for boundary inclusion
        if seg.source_start - 1e-5 <= source_t <= seg.source_end + 1e-5:
            fraction = (source_t - seg.source_start) / seg.source_duration
            out_start, out_end = offsets[i]
            out_t = out_start + (fraction * (out_end - out_start))
            results.append(round(out_t, 6))

    return results


def output_time_to_source_time(segments: List[TimelineSegment], output_t: float) -> Optional[Tuple[str, float]]:
    """
    Map an output time to (segment_id, source_t).
    Returns None if output_t is beyond output duration.
    """
    offsets = compute_segment_output_offsets(segments)
    for i, (out_start, out_end) in enumerate(offsets):
        if out_start - 1e-5 <= output_t <= out_end + 1e-5:
            seg = segments[i]
            frac = (output_t - out_start) / max(1e-9, (out_end - out_start))
            src_t = seg.source_start + frac * seg.source_duration
            return (seg.segment_id, round(src_t, 6))
    return None


def resolve_anchor_words_to_output_range(
    segments: List[TimelineSegment],
    words: List[TranscriptWord],
) -> Tuple[Optional[float], Optional[float], str]:
    """
    Given a list of words, resolve their source interval to output start and output end.
    Returns:
        (output_start, output_end, status)
        where status is:
        - "anchored": fully present in current timeline
        - "partially_cut": some part of the interval was cut
        - "removed": completely cut from timeline
    """
    if not words:
        return None, None, "removed"

    min_src_start = min(w.start for w in words)
    max_src_end = max(w.end for w in words)

    out_starts = source_time_to_output_times(segments, min_src_start)
    out_ends = source_time_to_output_times(segments, max_src_end)

    if not out_starts and not out_ends:
        # Check if any segment overlaps the interval
        overlaps = [
            seg for seg in segments
            if max(seg.source_start, min_src_start) < min(seg.source_end, max_src_end)
        ]
        if not overlaps:
            return None, None, "removed"
        # Partially covered by a segment
        return None, None, "partially_cut"

    if out_starts and out_ends:
        # In simple chronological ordering, match first start with corresponding end
        start_t = out_starts[0]
        end_t = out_ends[-1]
        if end_t >= start_t:
            return start_t, end_t, "anchored"

    # If start is present but end is cut or vice versa
    return None, None, "partially_cut"
