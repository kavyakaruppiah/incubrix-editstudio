"""Integer-tick, source-anchored timeline replay.

This module is deliberately independent of FastAPI, storage and FFmpeg. Source
intervals are half-open ``[start_tick, end_tick)`` ranges. Playback rates are
integer ratios so the canonical timeline contains no floating-point values.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from typing import Any, Iterable, Literal

OpKind = Literal["cut", "keep", "speed", "move", "mute", "bleep", "caption"]
OpState = Literal["active", "undone", "disabled"]


@dataclass(frozen=True, slots=True)
class SourceWord:
    word_id: str
    start_tick: int
    end_tick: int
    text: str = ""
    speaker: str | None = None
    confidence_milli: int | None = None

    def __post_init__(self) -> None:
        if not self.word_id or self.start_tick < 0 or self.end_tick <= self.start_tick:
            raise ValueError("word requires an id and a positive, non-negative source interval")
        if self.confidence_milli is not None and not 0 <= self.confidence_milli <= 1000:
            raise ValueError("confidence_milli must be in [0, 1000]")


@dataclass(frozen=True, slots=True)
class EditOperation:
    op_id: str
    kind: OpKind
    state: OpState = "active"
    start_tick: int | None = None
    end_tick: int | None = None
    word_ids: tuple[str, ...] = ()
    anchor_tick: int | None = None
    speed_num: int = 1
    speed_den: int = 1
    text: str = ""

    def __post_init__(self) -> None:
        if not self.op_id:
            raise ValueError("op_id is required")
        if self.kind in {"cut", "keep", "speed", "move", "mute", "bleep"}:
            if self.start_tick is None or self.end_tick is None:
                raise ValueError(f"{self.kind} requires a source interval")
            if self.start_tick < 0 or self.end_tick <= self.start_tick:
                raise ValueError("source interval must be positive and non-negative")
        if self.kind == "move" and self.anchor_tick is None:
            raise ValueError("move requires a source anchor tick")
        if self.kind == "speed" and (self.speed_num <= 0 or self.speed_den <= 0):
            raise ValueError("speed ratio components must be positive integers")


@dataclass(frozen=True, slots=True)
class Segment:
    start_tick: int
    end_tick: int
    speed_num: int = 1
    speed_den: int = 1


@dataclass(frozen=True, slots=True)
class Timeline:
    duration_ticks: int
    words: tuple[SourceWord, ...] = ()
    history: tuple[EditOperation, ...] = ()
    cursor: int | None = None

    def __post_init__(self) -> None:
        if self.duration_ticks <= 0:
            raise ValueError("duration_ticks must be positive")
        if self.cursor is not None and not 0 <= self.cursor <= len(self.history):
            raise ValueError("cursor must be between 0 and history length")
        if any(w.end_tick > self.duration_ticks for w in self.words):
            raise ValueError("word exceeds source duration")


@dataclass(frozen=True, slots=True)
class DerivedCaption:
    op_id: str
    text: str
    visible_word_ids: tuple[str, ...]
    hidden: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DerivedAudioEffect:
    op_id: str
    kind: Literal["mute", "bleep"]
    source_intervals: tuple[tuple[int, int], ...]
    word_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DerivedTimeline:
    segments: tuple[Segment, ...]
    captions: tuple[DerivedCaption, ...]
    audio_effects: tuple[DerivedAudioEffect, ...]


def _subtract(segments: Iterable[Segment], start: int, end: int) -> list[Segment]:
    result: list[Segment] = []
    for seg in segments:
        if seg.end_tick <= start or seg.start_tick >= end:
            result.append(seg)
            continue
        if seg.start_tick < start:
            result.append(replace(seg, end_tick=start))
        if seg.end_tick > end:
            result.append(replace(seg, start_tick=end))
    return result


def _split_interval(segments: list[Segment], start: int, end: int) -> list[Segment]:
    out: list[Segment] = []
    for seg in segments:
        if seg.start_tick < start < seg.end_tick:
            out.extend((replace(seg, end_tick=start), replace(seg, start_tick=start)))
        else:
            out.append(seg)
    result: list[Segment] = []
    for seg in out:
        if seg.start_tick < end < seg.end_tick:
            result.extend((replace(seg, end_tick=end), replace(seg, start_tick=end)))
        else:
            result.append(seg)
    return result


def replay(timeline: Timeline, cursor: int | None = None) -> tuple[Segment, ...]:
    """Fold active operations over the immutable source in history order."""
    limit = len(timeline.history) if cursor is None else cursor
    if not 0 <= limit <= len(timeline.history):
        raise ValueError("cursor is outside history")
    segments = [Segment(0, timeline.duration_ticks)]
    for op in timeline.history[:limit]:
        if op.state != "active":
            continue
        start, end = op.start_tick, op.end_tick
        if end is not None and end > timeline.duration_ticks:
            raise ValueError(f"operation {op.op_id!r} exceeds source duration")
        if op.kind == "move" and (op.anchor_tick is None or op.anchor_tick > timeline.duration_ticks):
            raise ValueError(f"operation {op.op_id!r} has an invalid move anchor")
        if op.kind == "move" and start <= op.anchor_tick < end:  # type: ignore[operator]
            raise ValueError("move anchor cannot be inside the moved interval")
        if op.kind == "cut":
            segments = _subtract(segments, start, end)  # type: ignore[arg-type]
        elif op.kind == "keep":
            segments = [
                replace(seg, start_tick=max(seg.start_tick, start), end_tick=min(seg.end_tick, end))
                for seg in segments
                if max(seg.start_tick, start) < min(seg.end_tick, end)  # type: ignore[arg-type]
            ]
        elif op.kind == "speed":
            segments = _split_interval(segments, start, end)  # type: ignore[arg-type]
            segments = [
                replace(seg, speed_num=op.speed_num, speed_den=op.speed_den)
                if seg.start_tick >= start and seg.end_tick <= end else seg  # type: ignore[operator]
                for seg in segments
            ]
        elif op.kind == "move":
            # Move semantics reorder the retained source interval before its anchor.
            moved: list[Segment] = []
            remainder: list[Segment] = []
            for seg in _split_interval(segments, start, end):  # type: ignore[arg-type]
                (moved if seg.start_tick >= start and seg.end_tick <= end else remainder).append(seg  # type: ignore[operator]
                )
            insert_at = next((i for i, seg in enumerate(remainder) if seg.start_tick <= op.anchor_tick < seg.end_tick), len(remainder))
            segments = remainder[:insert_at] + moved + remainder[insert_at:]
    return tuple(segments)


def derive_timeline(timeline: Timeline, cursor: int | None = None) -> DerivedTimeline:
    """Replay timeline and resolve caption visibility against surviving source words."""
    limit = len(timeline.history) if cursor is None else cursor
    segments = replay(timeline, limit)
    word_by_id = {word.word_id: word for word in timeline.words}
    captions: list[DerivedCaption] = []
    audio_effects: list[DerivedAudioEffect] = []
    for op in timeline.history[:limit]:
        if op.state != "active":
            continue
        if op.kind in {"mute", "bleep"}:
            start, end = op.start_tick, op.end_tick
            effective = tuple(
                (max(start, seg.start_tick), min(end, seg.end_tick))
                for seg in segments
                if max(start, seg.start_tick) < min(end, seg.end_tick)  # type: ignore[arg-type]
            )
            audio_effects.append(DerivedAudioEffect(op.op_id, op.kind, effective, op.word_ids))
            continue
        if op.kind != "caption":
            continue
        surviving = tuple(
            word_id for word_id in op.word_ids
            if word_id in word_by_id and any(
                seg.start_tick < word_by_id[word_id].end_tick and seg.end_tick > word_by_id[word_id].start_tick
                for seg in segments
            )
        )
        captions.append(DerivedCaption(
            op_id=op.op_id,
            text=op.text,
            visible_word_ids=surviving,
            hidden=not surviving,
            warnings=("caption hidden because all anchored words are cut",) if op.word_ids and not surviving else (),
        ))
    return DerivedTimeline(segments=segments, captions=tuple(captions), audio_effects=tuple(audio_effects))


def src_to_out(timeline: Timeline, source_tick: int, cursor: int | None = None) -> tuple[int, ...]:
    """Map a source tick to output ticks (multiple values are possible after a move)."""
    offset_num = 0
    mapped: list[int] = []
    for seg in replay(timeline, cursor):
        duration_num = (seg.end_tick - seg.start_tick) * seg.speed_den
        duration = (duration_num + seg.speed_num // 2) // seg.speed_num
        if seg.start_tick <= source_tick <= seg.end_tick:
            local_num = (source_tick - seg.start_tick) * seg.speed_den
            mapped.append(offset_num + (local_num + seg.speed_num // 2) // seg.speed_num)
        offset_num += duration
    return tuple(mapped)


def out_to_src(timeline: Timeline, output_tick: int, cursor: int | None = None) -> tuple[int, int] | None:
    """Map an output tick to ``(segment_index, source_tick)`` using integer rounding."""
    offset = 0
    for index, seg in enumerate(replay(timeline, cursor)):
        duration = ((seg.end_tick - seg.start_tick) * seg.speed_den + seg.speed_num // 2) // seg.speed_num
        if offset <= output_tick <= offset + duration:
            local_out = output_tick - offset
            source_delta = (local_out * seg.speed_num + seg.speed_den // 2) // seg.speed_den
            return index, min(seg.end_tick, seg.start_tick + source_delta)
        offset += duration
    return None


def canonical_state(timeline: Timeline, cursor: int | None = None) -> dict[str, Any]:
    limit = len(timeline.history) if cursor is None else cursor
    return {
        "duration_ticks": timeline.duration_ticks,
        "words": [asdict(w) for w in timeline.words],
        "history": [asdict(op) for op in timeline.history[:limit]],
        "segments": [asdict(seg) for seg in replay(timeline, limit)],
    }


def canonical_hash(timeline: Timeline, cursor: int | None = None) -> str:
    payload = json.dumps(canonical_state(timeline, cursor), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def append_operation(timeline: Timeline, operation: EditOperation) -> Timeline:
    """Append an edit; after an undo, mark the redo branch disabled first."""
    history = list(timeline.history)
    if any(op.state == "undone" for op in history):
        history = [replace(op, state="disabled") if op.state == "undone" else op for op in history]
    history.append(operation)
    return replace(timeline, history=tuple(history), cursor=len(history))


def undo(timeline: Timeline) -> Timeline:
    history = list(timeline.history)
    index = next((i for i in range(len(history) - 1, -1, -1) if history[i].state == "active"), None)
    if index is None:
        return replace(timeline, cursor=len(history))
    history[index] = replace(history[index], state="undone")
    return replace(timeline, history=tuple(history), cursor=len(history))


def redo(timeline: Timeline) -> Timeline:
    history = list(timeline.history)
    index = next((i for i in range(len(history) - 1, -1, -1) if history[i].state == "undone"), None)
    if index is None:
        return replace(timeline, cursor=len(history))
    history[index] = replace(history[index], state="active")
    return replace(timeline, history=tuple(history), cursor=len(history))


def restore(timeline: Timeline, op_id: str) -> Timeline:
    history = list(timeline.history)
    index = next((i for i, op in enumerate(history) if op.op_id == op_id), None)
    if index is None:
        raise KeyError(f"operation {op_id!r} does not exist")
    history[index] = replace(history[index], state="disabled")
    return replace(timeline, history=tuple(history), cursor=len(history))
