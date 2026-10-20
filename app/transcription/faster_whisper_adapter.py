from typing import Optional, Tuple
from app.config import settings
from app.models.transcript import Transcript, TranscriptWord, normalize_text
from app.transcription.base import TranscriptionAdapter


class FasterWhisperAdapter(TranscriptionAdapter):
    def __init__(
        self,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        vad_filter: bool = True,
    ):
        self.model_size = model_size or getattr(settings, "WHISPER_MODEL_SIZE", "tiny")
        self.device = device or getattr(settings, "WHISPER_DEVICE", "cpu")
        self.compute_type = compute_type or ("int8" if self.device == "cpu" else "float16")
        self.vad_filter = vad_filter
        self._model = None

    def is_available(self) -> Tuple[bool, str]:
        try:
            import faster_whisper
            return True, f"faster-whisper library is installed. Configured model: {self.model_size} ({self.device}, {self.compute_type})."
        except ImportError:
            return (
                False,
                "faster-whisper is not installed. To enable local transcription, run: pip install faster-whisper. "
                "Alternatively, upload a word-level transcript directly via API/UI or use a fixture."
            )

    def transcribe(
        self,
        media_path: str,
        language: Optional[str] = "en",
        vad_filter: Optional[bool] = None,
    ) -> Transcript:
        available, msg = self.is_available()
        if not available:
            raise RuntimeError(msg)

        from faster_whisper import WhisperModel

        if self._model is None:
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )

        lang_arg = None if (language in (None, "", "auto")) else language
        vad = self.vad_filter if vad_filter is None else vad_filter

        segments, info = self._model.transcribe(
            media_path,
            language=lang_arg,
            word_timestamps=True,
            vad_filter=vad,
            beam_size=5,
        )

        detected_lang = getattr(info, "language", language or "en")
        lang_prob = getattr(info, "language_probability", 1.0)

        words = []
        word_idx = 1
        for segment in segments:
            if not segment.words:
                # If segment has no word breakdown, use segment as word
                cleaned = segment.text.strip()
                if cleaned:
                    conf = getattr(segment, "avg_logprob", None)
                    prob = 0.8 if conf is None else round(min(1.0, max(0.0, 1.0 + conf / 5.0)), 2)
                    warnings = ["Segment-level timestamp only"]
                    if prob < 0.5:
                        warnings.append("Low confidence speech segment")
                    words.append(
                        TranscriptWord(
                            id=f"w_{word_idx:04d}",
                            text=cleaned,
                            normalized_text=normalize_text(cleaned),
                            start=round(segment.start, 3),
                            end=round(segment.end, 3),
                            speaker=getattr(segment, "speaker", None),
                            confidence=prob,
                            provenance="faster_whisper",
                            warnings=warnings,
                        )
                    )
                    word_idx += 1
                continue

            for w in segment.words:
                cleaned = w.word.strip()
                if not cleaned:
                    continue
                conf = getattr(w, "probability", None)
                warnings = []
                if conf is not None and conf < 0.5:
                    warnings.append(f"Low confidence ({conf:.2f})")

                words.append(
                    TranscriptWord(
                        id=f"w_{word_idx:04d}",
                        text=cleaned,
                        normalized_text=normalize_text(cleaned),
                        start=round(w.start, 3),
                        end=round(w.end, 3),
                        speaker=getattr(segment, "speaker", None),
                        confidence=round(conf, 3) if conf is not None else None,
                        provenance="faster_whisper",
                        warnings=warnings,
                    )
                )
                word_idx += 1

        return Transcript(
            words=words,
            language=detected_lang,
            language_probability=round(lang_prob, 3) if lang_prob is not None else None,
        )
