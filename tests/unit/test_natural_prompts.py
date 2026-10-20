from app.engine.instruction_parser import InstructionParser
from app.models.media import MediaMetadata
from app.models.timeline import Timeline, TimelineSegment
from app.models.transcript import Transcript, TranscriptWord

def test_diverse_user_prompts():
    meta = MediaMetadata(duration=20.0, width=1280, height=720, video_codec="h264", audio_present=True, file_size=1000)
    seg = TimelineSegment(segment_id="seg_1", source_start=0.0, source_end=20.0, speed=1.0)
    words = [
        TranscriptWord(id="w1", text="Hello", start=1.0, end=1.5),
        TranscriptWord(id="w2", text="world", start=1.5, end=2.0),
        TranscriptWord(id="w3", text="um", start=3.0, end=3.5),
    ]
    tl = Timeline(
        media_id="test",
        original_media_hash="a" * 64,
        source_metadata=meta,
        transcript=Transcript(words=words),
        segments=[seg],
    )

    parser = InstructionParser()
    prompts = [
        "cut from 00:02 to 00:05",
        "cut 0 to 5",
        "cut 2-6",
        "trim 1 to 4",
        "cut first 3 seconds",
        "cut last 4 seconds",
        "keep only from 00:02 to 00:10",
        "keep first 10 seconds",
        "speed up 2x",
        "speed up from 0 to 5 by 1.5x",
        "slow down to 0.5x",
        "mute 1 to 3",
        "mute video",
        "bleep 2 to 4",
        "generate captions",
        "add captions",
        "captions",
        "subtitles",
        "remove filler words",
        "cut fillers",
        "remove silence",
        "undo",
        "redo",
        "reset",
        "start over",
        "remove word um",
        "cut phrase 'world'",
    ]

    for p in prompts:
        prop = parser.parse_instruction(p, tl)
        assert prop is not None
        assert prop.operation_type is not None
        print(f"PASS: '{p}' -> {prop.operation_type.value}")

if __name__ == "__main__":
    test_diverse_user_prompts()
