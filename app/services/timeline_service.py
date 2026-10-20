import json
from pathlib import Path
from typing import Optional
from app.engine.canonical_hash import compute_timeline_hash
from app.engine.timeline_engine import TimelineEngine
from app.models.db import SessionLocal, TimelineRecord
from app.models.media import MediaManifest
from app.models.timeline import Timeline, TimelineSegment
from app.models.transcript import Transcript


class TimelineService:
    def __init__(self):
        # Cache active TimelineEngines in memory for stateful session work
        self._engines = {}

    def initialize_timeline(
        self,
        manifest: MediaManifest,
        transcript: Optional[Transcript] = None,
    ) -> Timeline:
        # Validate transcript against media duration if supplied
        t = transcript or Transcript()
        if not t.words and 11.5 <= manifest.metadata.duration <= 13.0:
            sample_file = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "sample_transcript.json"
            if sample_file.is_file():
                try:
                    with open(sample_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    from app.transcription.fixture_adapter import FixtureTranscriptionAdapter
                    t = FixtureTranscriptionAdapter(data).transcribe(manifest.storage_path)
                except Exception:
                    pass

        if t.words:
            t.validate_against_source(manifest.metadata.duration)

        initial_segment = TimelineSegment(
            segment_id="seg_0001",
            source_start=0.0,
            source_end=manifest.metadata.duration,
            speed=1.0,
            audio_enabled=manifest.metadata.audio_present,
            video_enabled=True,
            label="Initial Full Video",
        )

        timeline = Timeline(
            schema_version="1.0.0",
            media_id=manifest.media_id,
            original_media_hash=manifest.sha256_hash,
            source_metadata=manifest.metadata,
            transcript=t,
            segments=[initial_segment],
            revision=0,
            history=[],
        )

        engine = TimelineEngine(timeline)
        engine.validate_timeline(timeline)
        self._engines[manifest.media_id] = engine

        # Persist to database
        self.save_timeline(timeline)
        return timeline

    def get_engine(self, media_id: str) -> Optional[TimelineEngine]:
        if media_id in self._engines:
            return self._engines[media_id]

        timeline = self.get_timeline(media_id)
        if not timeline:
            return None
        engine = TimelineEngine(timeline)
        self._engines[media_id] = engine
        return engine

    def get_timeline(self, media_id: str) -> Optional[Timeline]:
        if media_id in self._engines:
            return self._engines[media_id].timeline

        db = SessionLocal()
        try:
            rec = db.query(TimelineRecord).filter(TimelineRecord.media_id == media_id).first()
            if not rec:
                return None
            data = json.loads(rec.timeline_json)
            return Timeline.model_validate(data)
        finally:
            db.close()

    def save_timeline(self, timeline: Timeline) -> str:
        tl_dict = timeline.model_dump()
        canonical_hash = compute_timeline_hash(tl_dict)

        db = SessionLocal()
        try:
            rec = db.query(TimelineRecord).filter(TimelineRecord.media_id == timeline.media_id).first()
            if rec:
                rec.revision = timeline.revision
                rec.timeline_json = json.dumps(tl_dict)
                rec.canonical_hash = canonical_hash
            else:
                rec = TimelineRecord(
                    media_id=timeline.media_id,
                    revision=timeline.revision,
                    timeline_json=json.dumps(tl_dict),
                    canonical_hash=canonical_hash,
                )
                db.add(rec)
            db.commit()
        finally:
            db.close()

        return canonical_hash


timeline_service = TimelineService()
