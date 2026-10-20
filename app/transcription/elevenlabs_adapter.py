"""Optional ElevenLabs Scribe speech-to-text adapter."""

from pathlib import Path
from typing import Optional, Tuple

import httpx

from app.config import settings
from app.models.transcript import Transcript, TranscriptWord, normalize_text


class ElevenLabsTranscriptionAdapter:
    API_URL = "https://api.elevenlabs.io/v1/speech-to-text"

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None, timeout: Optional[float] = None):
        self.api_key = (api_key if api_key is not None else settings.ELEVENLABS_API_KEY or "").strip()
        self.model_id = (model_id or settings.ELEVENLABS_STT_MODEL).strip()
        self.timeout = timeout or settings.ELEVENLABS_API_TIMEOUT_SECONDS

    def is_available(self) -> Tuple[bool, str]:
        if not self.api_key:
            return False, "Set ELEVENLABS_API_KEY to use ElevenLabs Scribe transcription."
        return True, f"ElevenLabs Scribe transcription is configured ({self.model_id})."

    def transcribe(self, media_path: str, language: Optional[str] = "auto") -> Transcript:
        available, message = self.is_available()
        if not available:
            raise RuntimeError(message)
        source = Path(media_path)
        if not source.is_file():
            raise FileNotFoundError(f"Media file not found: {media_path}")

        data = {
            "model_id": self.model_id,
            "timestamps_granularity": "word",
            "diarize": "true",
            "tag_audio_events": "false",
        }
        lang = (language or "auto").strip().lower()
        if lang not in ("", "auto"):
            data["language_code"] = lang

        try:
            with source.open("rb") as media_file:
                response = httpx.post(
                    self.API_URL,
                    headers={"xi-api-key": self.api_key},
                    data=data,
                    files={"file": (source.name, media_file, "application/octet-stream")},
                    timeout=self.timeout,
                )
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as exc:
            # Keep credentials and local paths out of the surfaced provider error.
            raise RuntimeError(f"ElevenLabs transcription failed with HTTP {exc.response.status_code}.") from exc
        except (httpx.RequestError, ValueError) as exc:
            raise RuntimeError(f"Could not complete ElevenLabs transcription: {exc}") from exc

        raw_words = result.get("words") if isinstance(result, dict) else None
        if not isinstance(raw_words, list):
            raise RuntimeError("ElevenLabs returned a transcript without word-level timestamps.")

        words = []
        for item in raw_words:
            if not isinstance(item, dict) or item.get("type", "word") != "word":
                continue
            text = str(item.get("text") or "").strip()
            start, end = item.get("start"), item.get("end")
            if not text or not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
                continue
            logprob = item.get("logprob")
            confidence = None
            if isinstance(logprob, (int, float)):
                import math
                confidence = round(max(0.0, min(1.0, math.exp(float(logprob)))), 3)
            words.append(TranscriptWord(
                id=f"el_{len(words) + 1:06d}",
                text=text,
                normalized_text=normalize_text(text),
                start=round(float(start), 3),
                end=round(float(end), 3),
                speaker=item.get("speaker_id"),
                confidence=confidence,
                provenance="elevenlabs_scribe",
            ))

        language_code = str(result.get("language_code") or language or "en").lower()
        language_code = {"eng": "en", "tam": "ta", "hin": "hi"}.get(language_code, language_code)
        probability = result.get("language_probability")
        return Transcript(
            words=words,
            language=language_code,
            language_probability=float(probability) if isinstance(probability, (int, float)) else None,
        )
