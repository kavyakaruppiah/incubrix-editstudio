#!/usr/bin/env python3
"""Measure cold local-planner latency with synthetic 5m and 60m transcripts.

This excludes transcription and rendering. It clears the parse cache before
each request so measurements do not accidentally report cache-hit latency.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import settings
from app.engine.parse_cache import parse_cache
from app.engine.timeline_engine import TimelineEngine
from app.models.media import MediaMetadata
from app.models.timeline import Timeline, TimelineSegment
from app.models.transcript import Transcript, TranscriptWord
from app.providers.ollama_instruction import OllamaInstructionAdapter
from app.services.plan_service import AIPlanService
from app.services.timeline_service import timeline_service


PROMPTS = [
    "Remove what the guest says about their previous employment",
    "Cut the portion where the visitor brings up their compensation",
    "Please take out the discussion around subscription costs",
    "Find and remove the guest's remarks about their former workplace",
    "Delete the part about pricing that the interviewee mentions",
]
TRANSCRIPT_LINES = [
    ("the host introduces the guest and welcomes everyone to the conversation", "Host"),
    ("the guest talks about their previous employment and former workplace", "Guest"),
    ("the visitor brings up their compensation and salary expectations", "Guest"),
    ("the interview discusses subscription costs pricing and monthly fees", "Host"),
    ("the guest explains the project and answers a question from the host", "Guest"),
]


def build_timeline(media_id: str, duration_s: float) -> Timeline:
    target_word_count = int(duration_s * 130 / 60)
    raw_words = []
    line_index = 0
    while len(raw_words) < target_word_count:
        line, speaker = TRANSCRIPT_LINES[line_index % len(TRANSCRIPT_LINES)]
        raw_words.extend((token, speaker) for token in re.findall(r"[\w']+", line))
        line_index += 1
    raw_words = raw_words[:target_word_count]
    seconds_per_word = duration_s / max(1, target_word_count)
    transcript_words = [
        TranscriptWord(
            id=f"{media_id}_w{index:06d}", text=token,
            start=index * seconds_per_word,
            end=min(duration_s, (index + 0.75) * seconds_per_word),
            speaker=speaker, confidence=0.93,
        )
        for index, (token, speaker) in enumerate(raw_words)
    ]
    metadata = MediaMetadata(
        duration=duration_s, width=1920, height=1080, frame_rate=30,
        video_codec="h264", audio_present=True, file_size=100_000_000,
    )
    return Timeline(
        media_id=media_id, original_media_hash="b" * 64,
        source_metadata=metadata,
        transcript=Transcript(words=transcript_words, language="en"),
        segments=[TimelineSegment(segment_id="seg_0001", source_start=0, source_end=duration_s)],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5, help="Cold planner requests per clip length (default: 5)")
    parser.add_argument("--output", type=Path, help="Optional JSON report output path")
    args = parser.parse_args()
    if args.runs < 1 or args.runs > 20:
        parser.error("--runs must be between 1 and 20")

    available, message = OllamaInstructionAdapter().is_available()
    if not available:
        parser.error(f"Configured Ollama planner is unavailable: {message}")

    settings.INSTRUCTION_PROVIDER = "ollama"
    service = AIPlanService()
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "synthetic 130 wpm transcript; cold parse cache; excludes transcription/rendering",
        "model": settings.OLLAMA_MODEL,
        "runs_per_duration": args.runs,
        "durations": {},
    }
    for label, duration_s in (("5m", 300.0), ("60m", 3600.0)):
        timeline = build_timeline(f"latency_{label}", duration_s)
        timeline_service._engines[timeline.media_id] = TimelineEngine(timeline)
        observations = []
        for index in range(args.runs):
            parse_cache.clear()
            started = time.perf_counter()
            try:
                result = service.generate_plan(timeline.media_id, PROMPTS[index % len(PROMPTS)])
                elapsed = time.perf_counter() - started
                observations.append({
                    "seconds": round(elapsed, 4),
                    "provider": result.get("instruction_provider"),
                    "supported_count": result.get("supported_count"),
                    "operations_count": result.get("operations_count"),
                })
            except Exception as exc:  # Keep failed requests visible in the report.
                observations.append({
                    "seconds": round(time.perf_counter() - started, 4),
                    "error_type": type(exc).__name__,
                })
        durations = [item["seconds"] for item in observations]
        report["durations"][label] = {
            "transcript_word_count": len(timeline.transcript.words),
            "median_seconds": round(statistics.median(durations), 4),
            "slowest_seconds": round(max(durations), 4),
            "observations": observations,
        }
    serialized = json.dumps(report, indent=2, ensure_ascii=False)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
