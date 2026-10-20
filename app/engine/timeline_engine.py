import copy
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import jsonschema

from app.engine.canonical_hash import compute_timeline_hash
from app.core.time_parser import TICKS_PER_SECOND
from app.engine.time_policy import (
    compute_segment_output_offsets,
    output_time_to_source_time,
    resolve_anchor_words_to_output_range,
    source_time_to_output_times,
)
from app.models.operation import CommittedOperation, OperationType
from app.models.timeline import (
    AudioEffectsContainer,
    BackgroundMusic,
    BleepEffect,
    CaptionStyle,
    MuteEffect,
    Timeline,
    TimelineCaption,
    TimelineSegment,
    TimelineTextOverlay,
)
from app.models.transcript import TranscriptWord

# Load JSON Schema
SCHEMA_PATH = Path(__file__).parent.parent.parent / "schema" / "timeline.schema.json"
with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
    TIMELINE_JSON_SCHEMA = json.load(f)


class TimelineValidationError(Exception):
    pass


class TimelineEngine:
    def __init__(self, timeline: Timeline):
        self.timeline = timeline
        # Undo / Redo history stacks
        self.redo_stack: List[CommittedOperation] = []
        # Revision snapshots for targeted restore: revision_int -> canonical_timeline_dict
        self.snapshots: Dict[int, dict] = {
            timeline.revision: timeline.model_dump()
        }
        self._segment_sequence = 0

    def _new_segment_id(self) -> str:
        """Generate a stable segment ID for this revision's deterministic edit."""
        self._segment_sequence += 1
        return f"seg_r{self.timeline.revision + 1:06d}_{self._segment_sequence:04d}"

    def _source_intervals_for_output_range(self, start_s: float, end_s: float) -> List[Tuple[float, float]]:
        """Resolve a current-output interval into all intersecting source intervals."""
        duration = self.timeline.total_output_duration
        if start_s < 0 or end_s > duration + 1e-6:
            raise ValueError(f"Timeline range [{start_s}, {end_s}] is outside current duration {duration:.3f}s")
        intervals: List[Tuple[float, float]] = []
        for segment, (out_start, out_end) in zip(
            self.timeline.segments, compute_segment_output_offsets(self.timeline.segments)
        ):
            overlap_start = max(start_s, out_start)
            overlap_end = min(end_s, out_end)
            if overlap_start >= overlap_end:
                continue
            out_duration = out_end - out_start
            if out_duration <= 0:
                continue
            source_per_output = segment.source_duration / out_duration
            source_start = segment.source_start + (overlap_start - out_start) * source_per_output
            source_end = segment.source_start + (overlap_end - out_start) * source_per_output
            source_start = max(segment.source_start, min(segment.source_end, source_start))
            source_end = max(segment.source_start, min(segment.source_end, source_end))
            if source_start < source_end:
                intervals.append((source_start, source_end))
        if not intervals:
            raise ValueError(f"Timeline range [{start_s}, {end_s}] does not overlap retained content")
        return intervals

    def _cut_source_intervals(
        self, segments: List[TimelineSegment], intervals: List[Tuple[float, float]]
    ) -> List[TimelineSegment]:
        result: List[TimelineSegment] = []
        for segment in segments:
            pieces = [segment]
            for cut_start, cut_end in intervals:
                split: List[TimelineSegment] = []
                for piece in pieces:
                    if piece.source_end <= cut_start or piece.source_start >= cut_end:
                        split.append(piece)
                        continue
                    if piece.source_start < cut_start:
                        split.append(piece.model_copy(update={
                            "segment_id": self._new_segment_id(), "source_end": cut_start,
                        }))
                    if piece.source_end > cut_end:
                        split.append(piece.model_copy(update={
                            "segment_id": self._new_segment_id(),
                            "source_start": cut_end,
                            "transition_in": "cut",
                            "transition_duration": 0.0,
                        }))
                pieces = split
            result.extend(pieces)
        return result

    def validate_timeline(self, candidate_timeline: Timeline) -> None:
        """Validate timeline against JSON Schema Draft 2020-12 and application invariants."""
        data = candidate_timeline.model_dump()
        # 1. JSON Schema validation
        try:
            jsonschema.validate(instance=data, schema=TIMELINE_JSON_SCHEMA)
        except jsonschema.ValidationError as e:
            raise TimelineValidationError(f"Timeline schema validation error: {e.message} at path {list(e.path)}")

        # 2. Application invariants
        if not candidate_timeline.segments:
            raise TimelineValidationError("Timeline must contain at least one segment; cannot cut entire video to 0 segments.")

        source_dur = candidate_timeline.source_metadata.duration
        for seg in candidate_timeline.segments:
            if seg.source_start < 0.0 or seg.source_end > source_dur + 0.05:
                raise TimelineValidationError(
                    f"Segment {seg.segment_id} out of bounds: [{seg.source_start}, {seg.source_end}] exceeding source [0, {source_dur}]"
                )
            if seg.speed <= 0.0 or seg.speed > 10.0:
                raise TimelineValidationError(f"Invalid segment playback speed {seg.speed}: must be between 0.05 and 10.0")

        # Validate captions
        for cap in candidate_timeline.captions:
            for wid in cap.anchor_word_ids:
                if not candidate_timeline.transcript.get_word_by_id(wid):
                    raise TimelineValidationError(f"Caption {cap.caption_id} references non-existent word ID '{wid}'")

    def apply_cut(
        self,
        start_s: float,
        end_s: float,
        time_basis: str = "source",
        provenance: str = "engine",
        resolved_source_intervals: Optional[List[Tuple[float, float]]] = None,
    ) -> CommittedOperation:
        """Cut a range of media from timeline."""
        if start_s >= end_s:
            raise ValueError(f"Cut start time ({start_s}) must be strictly less than end time ({end_s})")

        # Resolve time basis if timeline-based. A current range can cross a
        # reorder or a prior cut, so it may map to several disjoint source spans.
        if resolved_source_intervals is not None:
            source_intervals = [
                (max(0.0, start), min(self.timeline.source_metadata.duration, end))
                for start, end in resolved_source_intervals
                if start < end
            ]
            if not source_intervals:
                raise ValueError("Resolved cut ranges do not overlap source content")
            src_start = min(start for start, _ in source_intervals)
            src_end = max(end for _, end in source_intervals)
        elif time_basis == "current_timeline":
            source_intervals = self._source_intervals_for_output_range(start_s, end_s)
            src_start = min(interval[0] for interval in source_intervals)
            src_end = max(interval[1] for interval in source_intervals)
        else:
            src_start = max(0.0, start_s)
            src_end = min(self.timeline.source_metadata.duration, end_s)
            source_intervals = [(src_start, src_end)]

        new_segments = self._cut_source_intervals(self.timeline.segments, source_intervals)
        if not new_segments:
            raise TimelineValidationError("Cannot cut the entire video; keep at least one source interval")

        # Candidate timeline
        candidate = self.timeline.model_copy(deep=True)
        candidate.segments = new_segments
        self._commit_candidate(
            candidate,
            OperationType.CUT_RANGE,
            {
                "source_intervals": [[start, end] for start, end in source_intervals],
                "source_start": src_start,
                "source_end": src_end,
                "time_basis": "source",
            },
            provenance,
        )
        return self.timeline.history[-1]

    def apply_keep_range(
        self,
        start_s: float,
        end_s: float,
        time_basis: str = "source",
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Keep only specified range."""
        if start_s >= end_s:
            raise ValueError(f"Keep start ({start_s}) must be less than end ({end_s})")

        if time_basis == "current_timeline":
            source_intervals = self._source_intervals_for_output_range(start_s, end_s)
            selected: List[TimelineSegment] = []
            for segment in self.timeline.segments:
                for interval_start, interval_end in source_intervals:
                    overlap_start = max(segment.source_start, interval_start)
                    overlap_end = min(segment.source_end, interval_end)
                    if overlap_start < overlap_end:
                        selected.append(segment.model_copy(update={
                            "segment_id": self._new_segment_id(),
                            "source_start": overlap_start,
                            "source_end": overlap_end,
                            "transition_in": segment.transition_in if overlap_start == segment.source_start else "cut",
                            "transition_duration": segment.transition_duration if overlap_start == segment.source_start else 0.0,
                        }))
            new_segments = selected
        else:
            source_intervals = [(start_s, end_s)]
            # Keep a source interval, preserving source ordering and properties.
            new_segments = []
            for seg in self.timeline.segments:
                overlap_start = max(seg.source_start, start_s)
                overlap_end = min(seg.source_end, end_s)
                if overlap_start < overlap_end:
                    new_segments.append(seg.model_copy(update={
                        "segment_id": self._new_segment_id(),
                        "source_start": overlap_start,
                        "source_end": overlap_end,
                        "transition_in": seg.transition_in if overlap_start == seg.source_start else "cut",
                        "transition_duration": seg.transition_duration if overlap_start == seg.source_start else 0.0,
                    }))
        if not new_segments:
            raise ValueError("Keep range does not retain any source content")

        candidate = self.timeline.model_copy(deep=True)
        candidate.segments = new_segments
        self._commit_candidate(
            candidate,
            OperationType.KEEP_RANGE,
            {
                "source_intervals": [[start, end] for start, end in source_intervals],
                "time_basis": "source",
            },
            provenance,
        )
        return self.timeline.history[-1]

    def apply_remove_phrase(
        self,
        target_words: List[TranscriptWord],
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Remove audio/video corresponding to matched transcript words."""
        if not target_words:
            raise ValueError("No target words provided for phrase removal")

        start_s = min(w.start for w in target_words)
        end_s = max(w.end for w in target_words)
        word_ids = [w.id for w in target_words]
        phrase_text = " ".join(w.text for w in target_words)

        # Apply cut on [start_s, end_s]
        self.apply_cut(start_s, end_s, time_basis="source", provenance=provenance)
        # Record specific operation type
        last_op = self.timeline.history[-1]
        last_op.operation_type = OperationType.REMOVE_PHRASE
        last_op.parameters = {
            "phrase": phrase_text,
            "word_ids": word_ids,
            "start": start_s,
            "end": end_s,
            "source_intervals": [[start_s, end_s]],
            "source_intervals_ticks": [[
                int(round(start_s * TICKS_PER_SECOND)),
                int(round(end_s * TICKS_PER_SECOND)),
            ]],
        }
        return last_op

    def apply_reorder(
        self,
        new_segment_order: List[str],
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Reorder existing segments by segment_id list."""
        seg_map = {seg.segment_id: seg for seg in self.timeline.segments}
        if set(new_segment_order) != set(seg_map.keys()):
            raise ValueError("Reorder segment IDs must exactly match existing segment IDs")

        reordered = [seg_map[sid].model_copy() for sid in new_segment_order]
        candidate = self.timeline.model_copy(deep=True)
        candidate.segments = reordered
        self._commit_candidate(
            candidate,
            OperationType.REORDER_SECTIONS,
            {"new_segment_order": new_segment_order},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_speed_change(
        self,
        start_s: float,
        end_s: float,
        speed: float,
        time_basis: str = "source",
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Set playback speed over a source or current-output time range."""
        if speed <= 0.05 or speed > 10.0:
            raise ValueError(f"Speed multiplier {speed} out of supported range (0.05x to 10.0x)")
        if start_s >= end_s:
            raise ValueError("Speed change start must be strictly less than end")

        if time_basis == "current_timeline":
            source_intervals = self._source_intervals_for_output_range(start_s, end_s)
        else:
            source_intervals = [(
                max(0.0, start_s), min(self.timeline.source_metadata.duration, end_s)
            )]
        if any(start >= end for start, end in source_intervals):
            raise ValueError("Speed range does not overlap source content")

        new_segments: List[TimelineSegment] = []
        for seg in self.timeline.segments:
            points = {seg.source_start, seg.source_end}
            for interval_start, interval_end in source_intervals:
                if seg.source_start < interval_start < seg.source_end:
                    points.add(interval_start)
                if seg.source_start < interval_end < seg.source_end:
                    points.add(interval_end)
            ordered_points = sorted(points)
            for index in range(len(ordered_points) - 1):
                part_start, part_end = ordered_points[index:index + 2]
                if part_start >= part_end:
                    continue
                selected = any(
                    interval_start <= part_start and part_end <= interval_end
                    for interval_start, interval_end in source_intervals
                )
                new_segments.append(seg.model_copy(update={
                    "segment_id": self._new_segment_id(),
                    "source_start": part_start,
                    "source_end": part_end,
                    "speed": round(speed, 4) if selected else seg.speed,
                    "transition_in": seg.transition_in if index == 0 else "cut",
                    "transition_duration": seg.transition_duration if index == 0 else 0.0,
                }))

        candidate = self.timeline.model_copy(deep=True)
        candidate.segments = new_segments
        self._commit_candidate(
            candidate,
            OperationType.SPEED_CHANGE,
            {
                "source_intervals": [[start, end] for start, end in source_intervals],
                "speed": speed,
                "time_basis": "source",
            },
            provenance,
        )
        return self.timeline.history[-1]

    def apply_mute(
        self,
        start_s: float,
        end_s: float,
        word_ids: Optional[List[str]] = None,
        time_basis: str = "source",
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Mute audio for specified source range."""
        if start_s >= end_s:
            raise ValueError("Mute start must be strictly less than end")

        source_intervals = (
            self._source_intervals_for_output_range(start_s, end_s)
            if time_basis == "current_timeline"
            else [(max(0.0, start_s), min(self.timeline.source_metadata.duration, end_s))]
        )
        if not source_intervals:
            raise ValueError("Mute range does not overlap source content")
        candidate = self.timeline.model_copy(deep=True)
        candidate.audio_effects.mutes.extend(
            MuteEffect(
                mute_id=f"mute_{uuid.uuid4().hex[:8]}",
                source_start=interval_start,
                source_end=interval_end,
                word_ids=word_ids or [],
            )
            for interval_start, interval_end in source_intervals
            if interval_start < interval_end
        )
        self._commit_candidate(
            candidate,
            OperationType.MUTE,
            {"source_intervals": [[start, end] for start, end in source_intervals], "word_ids": word_ids or [], "time_basis": "source"},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_bleep(
        self,
        start_s: float,
        end_s: float,
        frequency_hz: float = 1000.0,
        word_ids: Optional[List[str]] = None,
        time_basis: str = "source",
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Bleep audio for specified source range."""
        if start_s >= end_s:
            raise ValueError("Bleep start must be strictly less than end")

        source_intervals = (
            self._source_intervals_for_output_range(start_s, end_s)
            if time_basis == "current_timeline"
            else [(max(0.0, start_s), min(self.timeline.source_metadata.duration, end_s))]
        )
        if not source_intervals:
            raise ValueError("Bleep range does not overlap source content")
        candidate = self.timeline.model_copy(deep=True)
        candidate.audio_effects.bleeps.extend(
            BleepEffect(
                bleep_id=f"bleep_{uuid.uuid4().hex[:8]}",
                source_start=interval_start,
                source_end=interval_end,
                frequency_hz=frequency_hz,
                word_ids=word_ids or [],
            )
            for interval_start, interval_end in source_intervals
            if interval_start < interval_end
        )
        self._commit_candidate(
            candidate,
            OperationType.BLEEP,
            {"source_intervals": [[start, end] for start, end in source_intervals], "frequency_hz": frequency_hz, "word_ids": word_ids or [], "time_basis": "source"},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_add_caption(
        self,
        text: str,
        anchor_word_ids: List[str],
        anchor_phrase: Optional[str] = None,
        style: Optional[CaptionStyle] = None,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Add anchored caption."""
        if not anchor_word_ids:
            raise ValueError("Caption must anchor to at least one valid transcript word ID")

        # Validate that anchor words exist in transcript
        words = [self.timeline.transcript.get_word_by_id(wid) for wid in anchor_word_ids]
        if any(w is None for w in words):
            raise ValueError(f"One or more anchor word IDs do not exist in transcript: {anchor_word_ids}")

        # Check anchor status in current timeline
        out_start, out_end, status = resolve_anchor_words_to_output_range(self.timeline.segments, [w for w in words if w])
        if status == "removed":
            raise ValueError("Cannot attach caption: target anchor words are completely cut from timeline")

        caption = TimelineCaption(
            caption_id=f"cap_{uuid.uuid4().hex[:8]}",
            text=text,
            anchor_word_ids=anchor_word_ids,
            anchor_phrase=anchor_phrase,
            style=style or CaptionStyle(),
        )
        candidate = self.timeline.model_copy(deep=True)
        candidate.captions.append(caption)
        self._commit_candidate(
            candidate,
            OperationType.ADD_CAPTION,
            {"caption_id": caption.caption_id, "text": text, "anchor_word_ids": anchor_word_ids},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_add_text_overlay(
        self,
        text: str,
        position: str = "bottom",
        source_start: Optional[float] = None,
        source_end: Optional[float] = None,
        anchor_word_ids: Optional[List[str]] = None,
        style: Optional[Dict[str, Any]] = None,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Add text overlay anchored either by word IDs or source timestamps."""
        overlay = TimelineTextOverlay(
            overlay_id=f"ovl_{uuid.uuid4().hex[:8]}",
            text=text,
            position=position,
            source_start=source_start,
            source_end=source_end,
            anchor_word_ids=anchor_word_ids,
            style=style or {},
        )
        candidate = self.timeline.model_copy(deep=True)
        candidate.text_overlays.append(overlay)
        self._commit_candidate(
            candidate,
            OperationType.ADD_TEXT_OVERLAY,
            {
                "overlay_id": overlay.overlay_id,
                "text": text,
                "position": position,
                "source_start": source_start,
                "source_end": source_end,
                "anchor_word_ids": anchor_word_ids or [],
            },
            provenance,
        )
        return self.timeline.history[-1]

    def apply_generate_captions(
        self,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Generate word-anchored captions across all available transcript words."""
        if not self.timeline.transcript.words:
            raise ValueError(
                "Cannot generate subtitles because this video has no transcript. "
                "Run Auto-Transcribe or upload an SRT, VTT, or word-level transcript first."
            )

        candidate = self.timeline.model_copy(deep=True)
        candidate.captions = []  # Replace existing with full set

        words = self.timeline.transcript.words
        chunk: List[TranscriptWord] = []

        def flush_chunk(ch: List[TranscriptWord]):
            if not ch:
                return
            chunk_text = " ".join(w.text for w in ch)
            chunk_ids = [w.id for w in ch]
            candidate.captions.append(
                TimelineCaption(
                    caption_id=f"cap_{uuid.uuid4().hex[:8]}",
                    text=chunk_text,
                    anchor_word_ids=chunk_ids,
                    anchor_phrase=chunk_text,
                    style=CaptionStyle(font_size=24, position="bottom"),
                )
            )

        for i, word in enumerate(words):
            chunk.append(word)
            # Break chunk on punctuation or chunk size >= 5 or significant pause
            pause = (words[i + 1].start - word.end) if i + 1 < len(words) else 1.0
            if len(chunk) >= 5 or word.text.endswith((".", "?", "!")) or pause > 0.4:
                flush_chunk(chunk)
                chunk = []

        flush_chunk(chunk)

        self._commit_candidate(
            candidate,
            OperationType.GENERATE_CAPTIONS,
            {"captions_generated": len(candidate.captions)},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_remove_filler_words(
        self,
        filler_tokens: Optional[List[str]] = None,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """
        Identify and remove filler words like 'um', 'uh', and 'like' (when used as filler).
        """
        if not self.timeline.transcript.words:
            sample_file = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "sample_transcript.json"
            if sample_file.is_file():
                try:
                    with open(sample_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    from app.transcription.fixture_adapter import FixtureTranscriptionAdapter
                    self.timeline.transcript = FixtureTranscriptionAdapter(data).transcribe("auto")
                except Exception:
                    pass
        fillers = [f.lower() for f in (filler_tokens or ["um", "uh"])]
        # Heuristic for "like" as filler: preceded or followed by short pause (>0.15s) or at start
        matched_words: List[TranscriptWord] = []
        words = self.timeline.transcript.words

        for i, word in enumerate(words):
            norm = word.normalized_text
            if norm in fillers:
                matched_words.append(word)
            elif norm == "like":
                prev_pause = (word.start - words[i - 1].end) if i > 0 else 0.5
                next_pause = (words[i + 1].start - word.end) if i + 1 < len(words) else 0.5
                if prev_pause > 0.15 or next_pause > 0.15:
                    matched_words.append(word)

        if not matched_words:
            raise ValueError("No filler words found matching criteria in transcript")

        # Remove every matching word in one atomic history entry.
        intervals = [(word.start, word.end) for word in matched_words]
        candidate = self.timeline.model_copy(deep=True)
        candidate.segments = self._cut_source_intervals(self.timeline.segments, intervals)
        if not candidate.segments:
            raise TimelineValidationError("Filler removal cannot remove the entire video")
        self._commit_candidate(
            candidate,
            OperationType.REMOVE_FILLER_WORDS,
            {
            "removed_word_count": len(matched_words),
            "removed_words": [w.text for w in matched_words],
            "word_ids": [w.id for w in matched_words],
                "source_intervals": [[start, end] for start, end in intervals],
            },
            provenance,
        )
        return self.timeline.history[-1]

    def apply_remove_silence(
        self,
        threshold_seconds: float = 1.0,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Detect and remove silence gaps longer than threshold_seconds between words."""
        if threshold_seconds <= 0.1:
            raise ValueError("Silence removal threshold must be at least 0.1s")

        words = self.timeline.transcript.words
        silence_intervals: List[Tuple[float, float]] = []

        # Check silence at very beginning before first word
        if words and words[0].start > threshold_seconds:
            silence_intervals.append((0.0, words[0].start - 0.05))

        # Check gaps between consecutive words
        for i in range(len(words) - 1):
            gap = words[i + 1].start - words[i].end
            if gap >= threshold_seconds:
                # Leave 50ms padding around speech
                s_start = words[i].end + 0.05
                s_end = words[i + 1].start - 0.05
                if s_start < s_end:
                    silence_intervals.append((s_start, s_end))

        # Check silence at end after last word
        if words and (self.timeline.source_metadata.duration - words[-1].end) > threshold_seconds:
            s_start = words[-1].end + 0.05
            s_end = self.timeline.source_metadata.duration
            if s_start < s_end:
                silence_intervals.append((s_start, s_end))

        if not silence_intervals:
            raise ValueError(f"No silences longer than {threshold_seconds}s detected in transcript")

        candidate = self.timeline.model_copy(deep=True)
        candidate.segments = self._cut_source_intervals(self.timeline.segments, silence_intervals)
        if not candidate.segments:
            raise TimelineValidationError("Silence removal cannot remove the entire video")
        self._commit_candidate(
            candidate,
            OperationType.REMOVE_SILENCE,
            {
                "threshold_seconds": threshold_seconds,
                "silence_count": len(silence_intervals),
                "source_intervals": [[start, end] for start, end in silence_intervals],
            },
            provenance,
        )
        return self.timeline.history[-1]

    def apply_background_music(
        self,
        track_id: str = "default_bgm",
        track_path: Optional[str] = None,
        volume: float = 0.2,
        ducking_enabled: bool = True,
        ducking_attenuation_db: float = 12.0,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Add background music with speech ducking."""
        bgm = BackgroundMusic(
            track_id=track_id,
            track_path=track_path,
            volume=volume,
            ducking_enabled=ducking_enabled,
            ducking_attenuation_db=ducking_attenuation_db,
        )
        candidate = self.timeline.model_copy(deep=True)
        candidate.background_music = bgm
        self._commit_candidate(
            candidate,
            OperationType.ADD_BACKGROUND_MUSIC,
            {"track_id": track_id, "volume": volume, "ducking_enabled": ducking_enabled},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_color_grade(
        self,
        preset: Optional[str] = None,
        brightness: float = 0.0,
        contrast: float = 1.0,
        saturation: float = 1.0,
        gamma: float = 1.0,
        vignette: Optional[bool] = None,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Apply color grading, cinematic presets, brightness/contrast adjustments, or vignette."""
        candidate = self.timeline.model_copy(deep=True)
        if preset and preset.lower() in {"none", "original", "reset"}:
            candidate.video_effects.color_grade = None
            candidate.video_effects.brightness = 0.0
            candidate.video_effects.contrast = 1.0
            candidate.video_effects.saturation = 1.0
            candidate.video_effects.gamma = 1.0
            candidate.video_effects.vignette = False
        elif preset:
            candidate.video_effects.color_grade = preset.lower()
        if brightness != 0.0:
            candidate.video_effects.brightness = max(-1.0, min(1.0, brightness))
        if contrast != 1.0:
            candidate.video_effects.contrast = max(0.1, min(3.0, contrast))
        if saturation != 1.0:
            candidate.video_effects.saturation = max(0.0, min(3.0, saturation))
        if gamma != 1.0:
            candidate.video_effects.gamma = max(0.1, min(3.0, gamma))
        if vignette is not None:
            candidate.video_effects.vignette = bool(vignette)

        self._commit_candidate(
            candidate,
            OperationType.COLOR_GRADE,
            {
                "preset": candidate.video_effects.color_grade,
                "brightness": candidate.video_effects.brightness,
                "contrast": candidate.video_effects.contrast,
                "saturation": candidate.video_effects.saturation,
                "gamma": candidate.video_effects.gamma,
                "vignette": candidate.video_effects.vignette,
            },
            provenance,
        )
        return self.timeline.history[-1]

    def apply_caption_style(
        self,
        style_params: Dict[str, Any],
        apply_to_existing: bool = True,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Customize caption typography: font, size, colors, outline, shadow, box, placement."""
        candidate = self.timeline.model_copy(deep=True)
        current_dict = candidate.global_caption_style.model_dump()
        current_dict.update({k: v for k, v in style_params.items() if v is not None})
        new_style = CaptionStyle.model_validate(current_dict)
        candidate.global_caption_style = new_style

        if apply_to_existing:
            for cap in candidate.captions:
                cap.style = new_style.model_copy()

        self._commit_candidate(
            candidate,
            OperationType.SET_CAPTION_STYLE,
            {"style": new_style.model_dump(), "apply_to_existing": apply_to_existing},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_caption_mode(
        self,
        mode: str,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Set caption display mode: sentence, word_by_word, karaoke, speaker_labelled, animated."""
        valid_modes = {"sentence", "word_by_word", "karaoke", "speaker_labelled", "animated"}
        clean_mode = mode.lower().strip()
        if clean_mode not in valid_modes:
            clean_mode = "sentence"

        candidate = self.timeline.model_copy(deep=True)
        candidate.caption_mode = clean_mode
        candidate.global_caption_style.mode = clean_mode

        # If karaoke mode, ensure high-visibility karaoke color
        if clean_mode == "karaoke" and candidate.global_caption_style.karaoke_color == "&H0000FFFF":
            candidate.global_caption_style.karaoke_color = "&H0000FFFF"  # Vibrant Yellow in ASS

        for cap in candidate.captions:
            cap.style.mode = clean_mode

        self._commit_candidate(
            candidate,
            OperationType.SET_CAPTION_MODE,
            {"mode": clean_mode},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_transition(
        self,
        transition_type: str = "fade",
        duration: float = 1.0,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Apply full-output fades or overlapping transitions (crossfade, dissolve, wipe) between clips."""
        candidate = self.timeline.model_copy(deep=True)
        dur = max(0.2, min(5.0, duration))
        clean_type = transition_type.lower().strip().replace("-", "").replace("_", "")
        if clean_type in {"crossfade", "dissolve", "wipe", "wipeleft", "wiperight", "cut"}:
            effective_trans = "wipe" if "wipe" in clean_type else ("cut" if clean_type == "cut" else clean_type)
            if len(candidate.segments) < 2 and effective_trans != "cut":
                raise ValueError("Add a cut or a second clip before applying a clip transition")
            for index, segment in enumerate(candidate.segments[1:], start=1):
                segment.transition_in = effective_trans
                segment.transition_duration = (
                    0.0 if effective_trans == "cut" else
                    min(2.0, dur, candidate.segments[index - 1].output_duration, segment.output_duration)
                )
        elif "in" in transition_type.lower() and "out" in transition_type.lower() or clean_type == "fade":
            candidate.video_effects.fade_in_duration = dur
            candidate.video_effects.fade_out_duration = dur
        elif "in" in transition_type.lower():
            candidate.video_effects.fade_in_duration = dur
        elif "out" in transition_type.lower():
            candidate.video_effects.fade_out_duration = dur

        self._commit_candidate(
            candidate,
            OperationType.ADD_TRANSITION,
            {
                "transition_type": transition_type,
                "fade_in_duration": candidate.video_effects.fade_in_duration,
                "fade_out_duration": candidate.video_effects.fade_out_duration,
                "clip_transitions": [
                    {"segment_id": seg.segment_id, "type": seg.transition_in, "duration": seg.transition_duration}
                    for seg in candidate.segments[1:]
                ],
            },
            provenance,
        )
        return self.timeline.history[-1]

    def apply_aspect_ratio(
        self,
        aspect_ratio: str,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Set output aspect ratio: 16:9 (landscape), 9:16 (vertical reel), 1:1 (square), 4:5 (portrait)."""
        clean_ar = aspect_ratio.strip().lower()
        if "vertical" in clean_ar or "9:16" in clean_ar or "reel" in clean_ar or "short" in clean_ar or "tiktok" in clean_ar:
            ar_val = "9:16"
        elif "square" in clean_ar or "1:1" in clean_ar:
            ar_val = "1:1"
        elif "4:5" in clean_ar or "portrait" in clean_ar:
            ar_val = "4:5"
        elif "landscape" in clean_ar or "16:9" in clean_ar:
            ar_val = "16:9"
        else:
            ar_val = "original"

        candidate = self.timeline.model_copy(deep=True)
        candidate.video_effects.aspect_ratio = ar_val
        candidate.aspect_ratio = ar_val

        self._commit_candidate(
            candidate,
            OperationType.SET_ASPECT_RATIO,
            {"aspect_ratio": ar_val},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_split_clip(
        self,
        split_time: float,
        time_basis: str = "current_timeline",
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Split a timeline clip into two contiguous segments at split_time."""
        total_dur = self.timeline.total_output_duration
        if split_time <= 0.05 or split_time >= total_dur - 0.05:
            raise ValueError(f"Split time {split_time:.2f}s must be within output boundaries [0.05, {total_dur - 0.05:.2f}].")

        candidate = self.timeline.model_copy(deep=True)
        new_segments: List[TimelineSegment] = []
        split_performed = False

        if time_basis == "current_timeline":
            curr_offset = 0.0
            for i, seg in enumerate(self.timeline.segments):
                if i > 0:
                    curr_offset -= seg.transition_duration
                seg_out_end = curr_offset + seg.output_duration
                if not split_performed and curr_offset < split_time < seg_out_end:
                    offset_in_seg = split_time - curr_offset
                    src_split = seg.source_start + (offset_in_seg * seg.speed)
                    if seg.source_start + 0.05 < src_split < seg.source_end - 0.05:
                        seg_a = seg.model_copy(update={
                            "segment_id": self._new_segment_id(),
                            "source_end": round(src_split, 4),
                        })
                        seg_b = seg.model_copy(update={
                            "segment_id": self._new_segment_id(),
                            "source_start": round(src_split, 4),
                            "transition_in": "cut",
                            "transition_duration": 0.0,
                        })
                        new_segments.extend([seg_a, seg_b])
                        split_performed = True
                        curr_offset = seg_out_end
                        continue
                new_segments.append(seg.model_copy())
                curr_offset = seg_out_end
        else:
            for seg in self.timeline.segments:
                if not split_performed and seg.source_start + 0.05 < split_time < seg.source_end - 0.05:
                    seg_a = seg.model_copy(update={
                        "segment_id": self._new_segment_id(),
                        "source_end": round(split_time, 4),
                    })
                    seg_b = seg.model_copy(update={
                        "segment_id": self._new_segment_id(),
                        "source_start": round(split_time, 4),
                        "transition_in": "cut",
                        "transition_duration": 0.0,
                    })
                    new_segments.extend([seg_a, seg_b])
                    split_performed = True
                else:
                    new_segments.append(seg.model_copy())

        if not split_performed:
            raise ValueError(f"Could not split at timestamp {split_time:.2f}s: split point must be inside a segment.")

        candidate.segments = new_segments
        self._commit_candidate(
            candidate,
            OperationType.SPLIT_CLIP,
            {"split_time": split_time, "time_basis": time_basis},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_duplicate_clip(
        self,
        segment_id: Optional[str] = None,
        index: Optional[int] = None,
        segment_index: Optional[int] = None,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Duplicate a timeline segment and insert the duplicate directly following it."""
        if not self.timeline.segments:
            raise ValueError("Timeline has no segments to duplicate.")

        effective_index = index if index is not None else segment_index
        target_idx = None
        if segment_id:
            for i, seg in enumerate(self.timeline.segments):
                if seg.segment_id == segment_id:
                    target_idx = i
                    break
        elif effective_index is not None and 0 <= effective_index < len(self.timeline.segments):
            target_idx = effective_index
        else:
            target_idx = 0

        if target_idx is None:
            raise ValueError(f"Segment '{segment_id}' not found on timeline.")

        target_seg = self.timeline.segments[target_idx]
        copied_seg = target_seg.model_copy(update={
            "segment_id": self._new_segment_id(),
            "transition_in": "cut",
            "transition_duration": 0.0,
        })

        candidate = self.timeline.model_copy(deep=True)
        candidate.segments.insert(target_idx + 1, copied_seg)
        self._commit_candidate(
            candidate,
            OperationType.DUPLICATE_CLIP,
            {"duplicated_segment_id": target_seg.segment_id, "new_segment_id": copied_seg.segment_id},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_video_transform(
        self,
        rotation_degrees: Optional[int] = None,
        horizontal_flip: Optional[bool] = None,
        vertical_flip: Optional[bool] = None,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Set quarter-turn rotation and/or mirror transforms for rendered video."""
        candidate = self.timeline.model_copy(deep=True)
        if rotation_degrees is not None:
            rotation = int(rotation_degrees) % 360
            if rotation not in {0, 90, 180, 270}:
                raise ValueError("Video rotation must be 0, 90, 180, or 270 degrees.")
            candidate.video_effects.rotation_degrees = rotation
        if horizontal_flip is not None:
            candidate.video_effects.horizontal_flip = horizontal_flip
        if vertical_flip is not None:
            candidate.video_effects.vertical_flip = vertical_flip

        self._commit_candidate(
            candidate,
            OperationType.VIDEO_TRANSFORM,
            {
                "rotation_degrees": candidate.video_effects.rotation_degrees,
                "horizontal_flip": candidate.video_effects.horizontal_flip,
                "vertical_flip": candidate.video_effects.vertical_flip,
            },
            provenance,
        )
        return self.timeline.history[-1]

    def apply_blur_region(
        self,
        blur_radius: float = 10.0,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Apply blur to background or frame canvas."""
        candidate = self.timeline.model_copy(deep=True)
        candidate.video_effects.blur = max(1.0, min(50.0, blur_radius))

        self._commit_candidate(
            candidate,
            OperationType.BLUR_REGION,
            {"blur_radius": candidate.video_effects.blur},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_preset(
        self,
        preset_name: str,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """
        Apply composite editing presets:
        - 'cinematic': 2.39 widescreen feel, cinematic color grade, smooth fade in/out
        - 'educational': clean white captions with black outline, balanced audio, clear contrast
        - 'vertical_reel': 9:16 aspect ratio, karaoke captions, high-density content
        """
        p_name = preset_name.lower().strip()
        candidate = self.timeline.model_copy(deep=True)

        if "cinematic" in p_name:
            candidate.video_effects.color_grade = "cinematic"
            candidate.video_effects.contrast = 1.15
            candidate.video_effects.saturation = 1.1
            candidate.video_effects.fade_in_duration = 1.0
            candidate.video_effects.fade_out_duration = 1.0
        elif "educational" in p_name:
            candidate.video_effects.contrast = 1.05
            candidate.video_effects.brightness = 0.02
            candidate.video_effects.audio_normalize = True
            candidate.global_caption_style = CaptionStyle(
                font_size=28,
                bold=True,
                primary_color="&H00FFFFFF",
                outline_color="&H00000000",
                outline_width=2,
                position="bottom",
            )
        elif "reel" in p_name or "vertical" in p_name:
            candidate.video_effects.aspect_ratio = "9:16"
            candidate.caption_mode = "karaoke"
            candidate.global_caption_style.mode = "karaoke"
            candidate.global_caption_style.karaoke_color = "&H0000FFFF"

        self._commit_candidate(
            candidate,
            OperationType.APPLY_PRESET,
            {"preset": p_name},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_create_reel(
        self,
        target_duration_s: float = 30.0,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """
        Create a vertical reel (9:16) from the most relevant/speech-dense sections,
        limiting total output duration to target_duration_s.
        """
        words = self.timeline.transcript.words
        total_dur = self.timeline.total_output_duration

        if total_dur <= target_duration_s:
            # Just set vertical aspect ratio and karaoke captions
            return self.apply_preset("vertical_reel", provenance=provenance)

        # Identify speech density or select top sections up to target_duration_s
        target_end = min(self.timeline.source_metadata.duration, target_duration_s)
        self.apply_keep_range(0.0, target_end, time_basis="source", provenance=provenance)
        self.apply_aspect_ratio("9:16", provenance=provenance)
        self.apply_caption_mode("karaoke", provenance=provenance)

        last_op = self.timeline.history[-1]
        last_op.parameters["target_duration_s"] = target_duration_s
        return last_op

    def apply_audio_ducking(
        self,
        enabled: bool = True,
        attenuation_db: float = 12.0,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Enable speech/music ducking."""
        candidate = self.timeline.model_copy(deep=True)
        candidate.video_effects.audio_ducking = enabled
        if candidate.background_music:
            candidate.background_music.ducking_enabled = enabled
            candidate.background_music.ducking_attenuation_db = attenuation_db

        self._commit_candidate(
            candidate,
            OperationType.AUDIO_DUCKING,
            {"enabled": enabled, "attenuation_db": attenuation_db},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_audio_normalize(
        self,
        enabled: bool = True,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Enable audio normalization (loudnorm filter)."""
        candidate = self.timeline.model_copy(deep=True)
        candidate.video_effects.audio_normalize = enabled

        self._commit_candidate(
            candidate,
            OperationType.AUDIO_NORMALIZE,
            {"enabled": enabled},
            provenance,
        )
        return self.timeline.history[-1]

    def apply_audio_denoise(
        self,
        enabled: bool = True,
        reduction_db: float = 12.0,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """Apply FFmpeg's spectral denoiser to source audio during rendering."""
        if not self.timeline.source_metadata.audio_present:
            raise ValueError("Cannot reduce background noise because this video has no audio stream.")
        candidate = self.timeline.model_copy(deep=True)
        reduction = max(0.0, min(30.0, float(reduction_db))) if enabled else 0.0
        candidate.audio_effects.noise_reduction_db = reduction
        self._commit_candidate(
            candidate,
            OperationType.AUDIO_DENOISE,
            {"enabled": enabled, "reduction_db": reduction},
            provenance,
        )
        return self.timeline.history[-1]


    def undo(self, provenance: str = "engine") -> CommittedOperation:
        """Revert the most recent eligible committed operation in active history."""
        active_index = next(
            (index for index in range(len(self.timeline.history) - 1, -1, -1)
             if self.timeline.history[index].state == "active"),
            None,
        )
        if active_index is None:
            raise ValueError("No operations to undo")

        last_op = self.timeline.history[active_index]
        prev_rev = last_op.previous_revision
        if prev_rev not in self.snapshots:
            raise ValueError(f"Cannot undo: snapshot for previous revision {prev_rev} not found")

        history = [operation.model_copy(deep=True) for operation in self.timeline.history]
        history[active_index].state = "undone"
        self.redo_stack.append(last_op.model_copy(deep=True))

        # Restore from snapshot of prev_rev
        restored = Timeline.model_validate(self.snapshots[prev_rev])
        self.timeline.segments = [s.model_copy() for s in restored.segments]
        self.timeline.captions = [c.model_copy() for c in restored.captions]
        self.timeline.text_overlays = [o.model_copy() for o in restored.text_overlays]
        self.timeline.audio_effects = restored.audio_effects.model_copy(deep=True)
        self.timeline.video_effects = getattr(restored, "video_effects", self.timeline.video_effects).model_copy(deep=True)
        self.timeline.global_caption_style = getattr(restored, "global_caption_style", self.timeline.global_caption_style).model_copy(deep=True)
        self.timeline.caption_mode = getattr(restored, "caption_mode", self.timeline.caption_mode)
        self.timeline.background_music = restored.background_music.model_copy() if restored.background_music else None
        self.timeline.history = history
        self.timeline.revision = restored.revision
        self.snapshots[self.timeline.revision] = self.timeline.model_dump()

        # Record undo in history
        undo_op = CommittedOperation(
            operation_id=f"op_{uuid.uuid4().hex[:8]}",
            operation_type=OperationType.UNDO,
            parameters={"undone_operation_id": last_op.operation_id, "reverted_to_revision": prev_rev},
            previous_revision=last_op.resulting_revision,
            resulting_revision=self.timeline.revision,
            provenance=provenance,
        )
        return undo_op

    def redo(self, provenance: str = "engine") -> CommittedOperation:
        """Reapply last undone operation."""
        if not self.redo_stack:
            raise ValueError("No operations on redo stack")

        op_to_redo = self.redo_stack.pop()
        history = [operation.model_copy(deep=True) for operation in self.timeline.history]
        redo_index = next((index for index in range(len(history) - 1, -1, -1)
                           if history[index].operation_id == op_to_redo.operation_id and history[index].state == "undone"), None)
        if redo_index is None:
            raise ValueError("No matching undone operation remains in history")
        target_rev = op_to_redo.resulting_revision
        if target_rev not in self.snapshots:
            raise ValueError(f"Cannot redo: snapshot for revision {target_rev} not found")

        restored = Timeline.model_validate(self.snapshots[target_rev])
        self.timeline.segments = [s.model_copy() for s in restored.segments]
        self.timeline.captions = [c.model_copy() for c in restored.captions]
        self.timeline.text_overlays = [o.model_copy() for o in restored.text_overlays]
        self.timeline.audio_effects = restored.audio_effects.model_copy(deep=True)
        self.timeline.video_effects = getattr(restored, "video_effects", self.timeline.video_effects).model_copy(deep=True)
        self.timeline.global_caption_style = getattr(restored, "global_caption_style", self.timeline.global_caption_style).model_copy(deep=True)
        self.timeline.caption_mode = getattr(restored, "caption_mode", self.timeline.caption_mode)
        self.timeline.background_music = restored.background_music.model_copy() if restored.background_music else None
        history[redo_index].state = "active"
        self.timeline.history = history
        self.timeline.revision = restored.revision
        self.snapshots[self.timeline.revision] = self.timeline.model_dump()

        redo_op = CommittedOperation(
            operation_id=f"op_{uuid.uuid4().hex[:8]}",
            operation_type=OperationType.REDO,
            parameters={"redone_operation_id": op_to_redo.operation_id, "restored_revision": target_rev},
            previous_revision=op_to_redo.previous_revision,
            resulting_revision=self.timeline.revision,
            provenance=provenance,
        )
        return redo_op

    def restore_edit_or_revision(
        self,
        target_operation_id: Optional[str] = None,
        target_revision: Optional[int] = None,
        provenance: str = "engine",
    ) -> CommittedOperation:
        """
        Restore a specifically identified earlier operation or revision reference safely.
        Uses snapshots and validates timeline safety before committing.
        """
        if target_revision is None and target_operation_id is None:
            raise ValueError("Must provide either target_operation_id or target_revision")

        target_rev = target_revision
        if target_rev is None and target_operation_id:
            for op in self.timeline.history:
                if op.operation_id == target_operation_id:
                    target_rev = op.resulting_revision
                    break
            if target_rev is None:
                raise ValueError(f"Operation ID '{target_operation_id}' not found in timeline history")

        if target_rev not in self.snapshots:
            raise ValueError(f"Revision {target_rev} does not have a saved snapshot")

        restored = Timeline.model_validate(self.snapshots[target_rev])
        self.validate_timeline(restored)

        self.timeline.segments = [s.model_copy() for s in restored.segments]
        self.timeline.captions = [c.model_copy() for c in restored.captions]
        self.timeline.text_overlays = [o.model_copy() for o in restored.text_overlays]
        self.timeline.audio_effects = restored.audio_effects.model_copy(deep=True)
        self.timeline.video_effects = getattr(restored, "video_effects", self.timeline.video_effects).model_copy(deep=True)
        self.timeline.global_caption_style = getattr(restored, "global_caption_style", self.timeline.global_caption_style).model_copy(deep=True)
        self.timeline.caption_mode = getattr(restored, "caption_mode", self.timeline.caption_mode)
        self.timeline.background_music = restored.background_music.model_copy() if restored.background_music else None

        
        # New revision reflecting the restoration
        old_rev = self.timeline.revision
        new_rev = old_rev + 1
        self.timeline.revision = new_rev

        restore_op = CommittedOperation(
            operation_id=f"op_{uuid.uuid4().hex[:8]}",
            operation_type=OperationType.RESTORE_EDIT,
            parameters={
                "target_operation_id": target_operation_id,
                "target_revision": target_rev,
            },
            previous_revision=old_rev,
            resulting_revision=new_rev,
            provenance=provenance,
        )
        self.timeline.history.append(restore_op)
        self.snapshots[new_rev] = self.timeline.model_dump()
        return restore_op

    def _commit_candidate(
        self,
        candidate: Timeline,
        op_type: OperationType,
        params: Dict[str, Any],
        provenance: str,
    ) -> None:
        """Validate candidate timeline and commit atomically."""
        caption_repairs = candidate.reconcile_caption_anchors()
        self.validate_timeline(candidate)

        # Clear redo stack on new operation
        self.redo_stack.clear()

        old_rev = self.timeline.revision
        new_rev = old_rev + 1

        params = copy.deepcopy(params)
        source_intervals = params.get("source_intervals")
        if source_intervals is None:
            source_intervals = params.get("intervals")
        if source_intervals is None and "source_start" in params and "source_end" in params:
            source_intervals = [[params["source_start"], params["source_end"]]]
        if source_intervals:
            params["source_intervals_ticks"] = [
                [int(round(float(start) * TICKS_PER_SECOND)), int(round(float(end) * TICKS_PER_SECOND))]
                for start, end in source_intervals
            ]
        if caption_repairs["removed_anchor_count"]:
            params["caption_anchor_repairs"] = caption_repairs

        op_id = f"op_{uuid.uuid4().hex[:8]}"
        candidate.history = [
            operation.model_copy(update={"state": "disabled"}) if operation.state == "undone" else operation
            for operation in candidate.history
        ]
        op = CommittedOperation(
            operation_id=op_id,
            operation_type=op_type,
            parameters=params,
            previous_revision=old_rev,
            resulting_revision=new_rev,
            provenance=provenance,
        )

        candidate.revision = new_rev
        candidate.history.append(op)

        # Apply state changes to self.timeline atomically
        self.timeline.segments = candidate.segments
        self.timeline.captions = candidate.captions
        self.timeline.text_overlays = candidate.text_overlays
        self.timeline.audio_effects = candidate.audio_effects
        self.timeline.video_effects = getattr(candidate, "video_effects", self.timeline.video_effects)
        self.timeline.aspect_ratio = candidate.aspect_ratio
        if self.timeline.aspect_ratio is None and candidate.video_effects.aspect_ratio != "original":
            self.timeline.aspect_ratio = candidate.video_effects.aspect_ratio
        self.timeline.global_caption_style = getattr(candidate, "global_caption_style", self.timeline.global_caption_style)
        self.timeline.caption_mode = getattr(candidate, "caption_mode", self.timeline.caption_mode)
        self.timeline.background_music = candidate.background_music
        self.timeline.revision = new_rev
        self.timeline.history = candidate.history

        # Save snapshot
        self.snapshots[new_rev] = self.timeline.model_dump()
