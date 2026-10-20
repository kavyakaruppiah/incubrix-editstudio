import re
from typing import Any, Dict, List, Optional
from app.models.timeline import Timeline
from app.models.transcript import Transcript, TranscriptWord, normalize_text


class SmartSuggestion:
    def __init__(
        self,
        suggestion_id: str,
        suggestion_type: str,
        title: str,
        explanation: str,
        suggested_prompt: str,
        start: float,
        end: float,
        affected_word_ids: Optional[List[str]] = None,
        confidence: float = 0.9,
        impact: str = "medium",
    ):
        if suggestion_type in ("filler_word", "filler_words"):
            suggestion_type = "filler_words"
        elif suggestion_type in ("repeated_phrase", "repeated_words"):
            suggestion_type = "repeated_words"
        elif suggestion_type in ("topic_section", "topic_match"):
            suggestion_type = "topic_match"
        self.suggestion_id = suggestion_id
        self.suggestion_type = suggestion_type
        self.type = suggestion_type
        self.title = title
        self.explanation = explanation
        self.description = explanation
        self.suggested_prompt = suggested_prompt
        self.suggested_action = suggested_prompt
        self.start = round(start, 3)
        self.end = round(end, 3)
        self.affected_word_ids = affected_word_ids or []
        self.confidence = confidence
        self.impact = impact

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.suggestion_id,
            "type": self.suggestion_type,
            "title": self.title,
            "explanation": self.explanation,
            "description": self.explanation,
            "suggested_prompt": self.suggested_prompt,
            "suggested_action": self.suggested_prompt,
            "start": self.start,
            "end": self.end,
            "duration": round(self.end - self.start, 3),
            "affected_word_ids": self.affected_word_ids,
            "confidence": self.confidence,
            "impact": self.impact,
        }


class SmartSuggestionService:
    def analyze_timeline(
        self,
        timeline: Timeline,
        topic: Optional[str] = None,
        media_path: Optional[str] = None,
        as_objects: bool = False,
    ):
        suggestions: List[SmartSuggestion] = []
        words = timeline.transcript.words
        total_dur = timeline.total_output_duration

        # 1. Detect Long Pauses / Silences
        if words:
            for i in range(len(words) - 1):
                gap = words[i + 1].start - words[i].end
                if gap >= 1.0:
                    suggestions.append(
                        SmartSuggestion(
                            suggestion_id=f"sug_pause_{i}",
                            suggestion_type="long_pause",
                            title=f"Long Pause ({gap:.2f}s)",
                            explanation=f"A silent pause of {gap:.2f}s occurs between words '{words[i].text}' and '{words[i+1].text}'.",
                            suggested_prompt="remove all long pauses",
                            start=words[i].end,
                            end=words[i + 1].start,
                            confidence=0.95,
                            impact="high" if gap >= 2.0 else "medium",
                        )
                    )
                    p_start = words[i].end + 0.05
                    p_end = words[i + 1].start - 0.05
                    if p_start < p_end:
                        suggestions.append(
                            SmartSuggestion(
                                suggestion_id=f"sug_pause_{i}",
                                suggestion_type="long_pause",
                                title=f"Dead Air Pause ({gap:.2f}s)",
                                explanation=f"Long silence of {gap:.2f}s detected between '{words[i].text}' and '{words[i + 1].text}'.",
                                suggested_prompt=f"cut from {p_start:.2f} to {p_end:.2f}",
                                start=p_start,
                                end=p_end,
                            )
                        )

        # 2. Detect Filler Words ("um", "uh", "you know", "like")
        common_fillers = {"um", "uh", "erm", "ah"}
        for idx, w in enumerate(words):
            if w.normalized_text in common_fillers:
                suggestions.append(
                    SmartSuggestion(
                        suggestion_id=f"sug_filler_{idx}",
                        suggestion_type="filler_word",
                        title=f"Filler Word '{w.text}'",
                        explanation=f"Spoken hesitation token '{w.text}' at {w.start:.2f}s.",
                        suggested_prompt="remove filler words",
                        start=w.start,
                        end=w.end,
                        affected_word_ids=[w.id],
                    )
                )

        # 3. Detect Repeated Words or False Starts (e.g. "we we", "the the")
        for i in range(len(words) - 1):
            if words[i].normalized_text and words[i].normalized_text == words[i + 1].normalized_text:
                if (words[i + 1].start - words[i].end) < 0.6:
                    suggestions.append(
                        SmartSuggestion(
                            suggestion_id=f"sug_repeat_{i}",
                            suggestion_type="repeated_phrase",
                            title=f"Stutter / Repeat '{words[i].text}'",
                            explanation=f"Word '{words[i].text}' repeated consecutively at {words[i].start:.2f}s.",
                            suggested_prompt=f"cut from {words[i].start:.2f} to {words[i].end:.2f}",
                            start=words[i].start,
                            end=words[i].end,
                            affected_word_ids=[words[i].id],
                        )
                    )

        # 4. Caption Timing Issues (words too short or too long)
        for idx, w in enumerate(words):
            dur = w.end - w.start
            if dur < 0.08:
                suggestions.append(
                    SmartSuggestion(
                        suggestion_id=f"sug_cap_short_{idx}",
                        suggestion_type="caption_timing",
                        title=f"Sub-frame Word '{w.text}'",
                        explanation=f"Word duration {dur:.3f}s is extremely brief; may cause subtitle flicker.",
                        suggested_prompt="apply the same caption style to the entire video",
                        start=w.start,
                        end=w.end,
                        affected_word_ids=[w.id],
                        confidence=0.7,
                    )
                )

        # 5. Topic Relevance Filtering (if user requested a specific topic)
        if topic and words:
            q_norm = normalize_text(topic)
            topic_tokens = set(q_norm.split())
            matching_windows: List[Tuple[float, float, List[TranscriptWord]]] = []
            window_size = 8
            for i in range(0, len(words), 4):
                win = words[i : i + window_size]
                win_text = " ".join(w.normalized_text for w in win)
                score = sum(1 for tok in topic_tokens if tok in win_text)
                if score > 0:
                    matching_windows.append((win[0].start, win[-1].end, win))

            for idx, (m_start, m_end, win) in enumerate(matching_windows):
                snippet = " ".join(w.text for w in win[:4]) + "..."
                suggestions.append(
                    SmartSuggestion(
                        suggestion_id=f"sug_topic_{idx}",
                        suggestion_type="topic_section",
                        title=f"Topic Match: '{snippet}'",
                        explanation=f"Section relevant to '{topic}' found at {m_start:.2f}s - {m_end:.2f}s.",
                        suggested_prompt=f"keep only from {m_start:.2f} to {m_end:.2f}",
                        start=m_start,
                        end=m_end,
                        affected_word_ids=[w.id for w in win],
                        confidence=0.95,
                    )
                )

        # 6. Scene boundary detection if media file is available
        if media_path and not suggestions:
            try:
                import scenedetect
                from scenedetect import detect, ContentDetector
                scene_list = detect(media_path, ContentDetector(threshold=27.0))
                for idx, (s_start, s_end) in enumerate(scene_list[:5]):
                    suggestions.append(
                        SmartSuggestion(
                            suggestion_id=f"sug_scene_{idx}",
                            suggestion_type="scene_boundary",
                            title=f"Scene Boundary {idx + 1}",
                            explanation=f"Visual scene cut detected at {s_start.get_seconds():.2f}s.",
                            suggested_prompt=f"cut from {s_start.get_seconds():.2f} to {s_start.get_seconds() + 2.0:.2f}",
                            start=s_start.get_seconds(),
                            end=s_end.get_seconds(),
                        )
                    )
            except Exception:
                pass

        if as_objects:
            return suggestions
        return [s.to_dict() for s in suggestions]

    def generate_suggestions(
        self,
        timeline: Timeline,
        topic: Optional[str] = None,
        media_path: Optional[str] = None,
    ) -> List[SmartSuggestion]:
        return self.analyze_timeline(timeline, topic=topic, media_path=media_path, as_objects=True)


smart_suggestion_service = SmartSuggestionService()
SmartSuggestionsService = SmartSuggestionService
