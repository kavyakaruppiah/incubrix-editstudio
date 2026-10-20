#!/usr/bin/env python3
"""
Generate deterministic, offline test fixtures using real FFmpeg.
No external copyrighted assets or internet downloads required.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Add repo root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings


def generate_all_fixtures():
    fixtures_dir = Path(__file__).parent.parent / "tests" / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = settings.resolve_ffmpeg()

    # 1. Sample with audio: 12 seconds, 320x240, 30fps, 440Hz sine wave audio
    with_audio_path = fixtures_dir / "sample_with_audio.mp4"
    if not with_audio_path.exists():
        print(f"Generating {with_audio_path.name}...")
        cmd = [
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", "testsrc2=duration=12:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=12:sample_rate=48000",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(with_audio_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # 2. Sample without audio: 6 seconds, 320x240, 30fps, no audio stream
    no_audio_path = fixtures_dir / "sample_no_audio.mp4"
    if not no_audio_path.exists():
        print(f"Generating {no_audio_path.name}...")
        cmd = [
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", "testsrc2=duration=6:size=320x240:rate=30",
            "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(no_audio_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # 3. Sample transcript matching sample_with_audio.mp4 (12s total duration)
    # Includes:
    # - Repeated phrase: "welcome to" (at 0.5s by Speaker A, and at 8.0s by Speaker B)
    # - Filler words: "um" at 2.0s, "uh" at 5.5s, "like" at 7.0s
    # - Multi-speaker: "Speaker A" and "Speaker B"
    # - Silence gaps: 3.5s - 5.0s (1.5s gap)
    transcript_path = fixtures_dir / "sample_transcript.json"
    transcript_data = {
        "words": [
            {"id": "w_0001", "text": "Hello", "start": 0.1, "end": 0.4, "speaker": "Speaker A", "confidence": 0.98},
            {"id": "w_0002", "text": "and", "start": 0.4, "end": 0.5, "speaker": "Speaker A", "confidence": 0.95},
            {"id": "w_0003", "text": "welcome", "start": 0.5, "end": 0.9, "speaker": "Speaker A", "confidence": 0.99},
            {"id": "w_0004", "text": "to", "start": 0.9, "end": 1.1, "speaker": "Speaker A", "confidence": 0.97},
            {"id": "w_0005", "text": "the", "start": 1.1, "end": 1.3, "speaker": "Speaker A", "confidence": 0.96},
            {"id": "w_0006", "text": "show", "start": 1.3, "end": 1.7, "speaker": "Speaker A", "confidence": 0.99},
            # Filler word "um"
            {"id": "w_0007", "text": "um", "start": 2.0, "end": 2.4, "speaker": "Speaker A", "confidence": 0.90},
            {"id": "w_0008", "text": "today", "start": 2.5, "end": 2.9, "speaker": "Speaker A", "confidence": 0.95},
            {"id": "w_0009", "text": "we", "start": 2.9, "end": 3.1, "speaker": "Speaker A", "confidence": 0.94},
            {"id": "w_0010", "text": "discuss", "start": 3.1, "end": 3.5, "speaker": "Speaker A", "confidence": 0.98},
            # Silence gap: 3.5 to 5.2 (1.7s gap)
            {"id": "w_0011", "text": "uh", "start": 5.2, "end": 5.5, "speaker": "Speaker B", "confidence": 0.88},
            {"id": "w_0012", "text": "important", "start": 5.6, "end": 6.2, "speaker": "Speaker B", "confidence": 0.97},
            {"id": "w_0013", "text": "updates", "start": 6.2, "end": 6.8, "speaker": "Speaker B", "confidence": 0.98},
            # Filler word "like" with pauses around it
            {"id": "w_0014", "text": "like", "start": 7.0, "end": 7.3, "speaker": "Speaker B", "confidence": 0.91},
            {"id": "w_0015", "text": "video", "start": 7.4, "end": 7.8, "speaker": "Speaker B", "confidence": 0.96},
            # Second occurrence of "welcome to"
            {"id": "w_0016", "text": "welcome", "start": 8.0, "end": 8.4, "speaker": "Speaker B", "confidence": 0.99},
            {"id": "w_0017", "text": "to", "start": 8.4, "end": 8.6, "speaker": "Speaker B", "confidence": 0.97},
            {"id": "w_0018", "text": "our", "start": 8.6, "end": 8.9, "speaker": "Speaker B", "confidence": 0.95},
            {"id": "w_0019", "text": "community", "start": 8.9, "end": 9.5, "speaker": "Speaker B", "confidence": 0.99},
            {"id": "w_0020", "text": "confidential", "start": 9.8, "end": 10.5, "speaker": "Speaker B", "confidence": 0.96},
            {"id": "w_0021", "text": "goodbye", "start": 10.7, "end": 11.2, "speaker": "Speaker B", "confidence": 0.99},
        ]
    }
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript_data, f, indent=2)

    # 4. Corrupt media file for rejection testing
    corrupt_path = fixtures_dir / "corrupt_media.mp4"
    corrupt_path.write_bytes(b"This is not a real MP4 file, it is totally corrupt.")

    print("All fixtures generated successfully!")


if __name__ == "__main__":
    generate_all_fixtures()
