import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from app.models.transcript import Transcript, TranscriptWord, normalize_text
from app.transcription.base import TranscriptionAdapter


class FixtureTranscriptionAdapter(TranscriptionAdapter):
    """Offline deterministic transcript adapter from test fixtures or user-provided files."""

    def __init__(self, fixture_data: Optional[Union[dict, list, str, Path]] = None):
        self.fixture_data = fixture_data

    def is_available(self) -> Tuple[bool, str]:
        return True, "Fixture transcript adapter is ready for offline tests and user transcripts."

    def transcribe(self, media_path: str, language: Optional[str] = "en") -> Transcript:
        if self.fixture_data is None:
            raise ValueError("No fixture data provided to FixtureTranscriptionAdapter")

        data = self.fixture_data
        if isinstance(data, (str, Path)):
            p = Path(data)
            if p.is_file():
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = json.loads(str(data))

        if isinstance(data, dict) and "words" in data:
            word_list = data["words"]
        elif isinstance(data, list):
            word_list = data
        else:
            raise ValueError("Invalid fixture format: expected dict with 'words' or list of word dicts")

        parsed_words: List[TranscriptWord] = []
        for idx, item in enumerate(word_list):
            raw_text = str(item.get("text", "")).strip()
            word_id = str(item.get("id") or f"w_{idx+1:04d}")
            parsed_words.append(
                TranscriptWord(
                    id=word_id,
                    text=raw_text,
                    normalized_text=item.get("normalized_text") or normalize_text(raw_text),
                    start=float(item.get("start", 0.0)),
                    end=float(item.get("end", 0.0)),
                    speaker=item.get("speaker"),
                    confidence=float(item["confidence"]) if item.get("confidence") is not None else None,
                    provenance=item.get("provenance", "fixture"),
                    warnings=item.get("warnings", []),
                )
            )

        return Transcript(words=parsed_words)
