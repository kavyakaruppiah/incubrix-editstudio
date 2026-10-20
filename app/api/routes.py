import json
import hashlib
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings
from app.engine.canonical_hash import compute_timeline_hash
from app.engine.time_policy import requested_time_basis, time_policy_statement
from app.jobs.job_manager import job_manager
from app.models.media import MediaManifest
from app.models.operation import InstructionResult, InstructionStatus, OperationType
from app.models.render import JobStatus, RenderManifest
from app.models.timeline import Timeline
from app.models.transcript import Transcript
from app.rendering.probe import probe_media_file
from app.schemas.api_schemas import (
    ApiErrorResponse,
    ClarificationAnswerRequest,
    EditWordRequest,
    HealthResponse,
    InstructionRequest,
    ReadinessResponse,
    RenderJobResponse,
    RenderOptions,
    RestoreRequest,
    SessionRunRequest,
)
from app.models.timeline import BackgroundMusic
from app.services.instruction_service import instruction_service
from app.services.media_service import media_service
from app.services.plan_service import plan_service
from app.services.project_service import project_service
from app.services.render_service import render_service
from app.services.session_service import execute_session
from app.services.timeline_service import timeline_service
from app.services.otio_export import timeline_to_otio
from app.providers.ollama_instruction import OllamaInstructionAdapter, OllamaProviderError
from app.transcription.faster_whisper_adapter import FasterWhisperAdapter
from app.transcription.fixture_adapter import FixtureTranscriptionAdapter
from app.utils.ffmpeg_check import check_ffmpeg_and_ffprobe
from app.utils.idempotency import idempotency_store

router = APIRouter(prefix="/api/v1")


def handle_idempotency_check(key: Optional[str], payload: Any) -> Optional[Response]:
    # Direct Python callers (including in-process service tests) see FastAPI's
    # Header marker as the default value; only an actual HTTP string is a key.
    if not isinstance(key, str) or not key.strip():
        return None
    chk_status, rec = idempotency_store.check(key, payload)
    if chk_status == "cached" and rec:
        return JSONResponse(status_code=rec.status_code, content=rec.response_data)
    elif chk_status == "conflict":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key reuse with materially different request payload is rejected.",
        )
    elif chk_status == "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An identical request with this idempotency key is still in progress.",
        )
    return None


def save_idempotency_record(key: Optional[str], payload: Any, status_code: int, response_data: Dict[str, Any]):
    if isinstance(key, str) and key.strip():
        idempotency_store.save(key, payload, status_code, response_data)


# 1. Health and Readiness
@router.get("/health", response_model=HealthResponse)
def get_health():
    return HealthResponse(status="ok", version="1.0.0")


@router.get("/ready", response_model=ReadinessResponse)
def get_readiness():
    ffmpeg_ok, ffmpeg_info = check_ffmpeg_and_ffprobe()
    transcription_available, transcription_message = FasterWhisperAdapter().is_available()
    ffmpeg_info["transcription_library_available"] = transcription_available
    ffmpeg_info["transcription_message"] = transcription_message
    ffmpeg_info["instruction_provider"] = settings.INSTRUCTION_PROVIDER
    if settings.INSTRUCTION_PROVIDER.strip().lower() in ("ollama", "auto"):
        try:
            ollama_available, ollama_message = OllamaInstructionAdapter(
                timeout=min(settings.OLLAMA_TIMEOUT_SECONDS, 2.0)
            ).is_available()
        except OllamaProviderError as exc:
            ollama_available, ollama_message = False, str(exc)
        ffmpeg_info["ollama_available"] = ollama_available
        ffmpeg_info["ollama_message"] = ollama_message
    # Check storage writability
    storage_ok = False
    test_file = Path(settings.LOCAL_STORAGE_DIR) / ".probe_write_test"
    try:
        test_file.write_text("ok")
        test_file.unlink()
        storage_ok = True
    except Exception as e:
        ffmpeg_info["storage_error"] = str(e)

    overall_ready = ffmpeg_ok and storage_ok
    status_str = "ready" if overall_ready else "not_ready"

    return ReadinessResponse(
        status=status_str,
        ffmpeg_available=ffmpeg_ok,
        ffprobe_available=ffmpeg_ok,
        storage_writable=storage_ok,
        details=ffmpeg_info,
    )


# 2. Media Upload & Inspection
@router.post("/media/upload", response_model=MediaManifest)
async def upload_media(
    file: UploadFile = File(...),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    # Include content hash so same-name uploads with different bytes never replay.
    upload_request = {"filename": file.filename}
    if idempotency_key:
        digest = hashlib.sha256()
        file.file.seek(0)
        while chunk := file.file.read(1024 * 1024):
            digest.update(chunk)
        file.file.seek(0)
        upload_request["sha256"] = digest.hexdigest()
    cached = handle_idempotency_check(idempotency_key, upload_request)
    if cached:
        return cached

    try:
        manifest = media_service.intake_uploaded_file(
            file.file, file.filename, content_length=getattr(file, "size", None)
        )
        # Initialize an empty timeline right away
        timeline_service.initialize_timeline(manifest, Transcript())
        resp_data = manifest.model_dump()
        save_idempotency_record(idempotency_key, upload_request, 200, resp_data)
        return manifest
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/media/{media_id}", response_model=MediaManifest)
def get_media_manifest(media_id: str):
    manifest = media_service.get_media_manifest(media_id)
    if not manifest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Media ID '{media_id}' not found")
    return manifest


@router.get("/media/{media_id}/source")
def stream_source_media(media_id: str):
    """Serve the immutable uploaded asset for browser playback and seeking."""
    manifest = media_service.get_media_manifest(media_id)
    if not manifest or not Path(manifest.storage_path).is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Media source '{media_id}' not found")
    media_type = mimetypes.guess_type(manifest.original_filename)[0] or "application/octet-stream"
    return FileResponse(manifest.storage_path, media_type=media_type)


@router.get("/media/{media_id}/scenes")
def get_media_scenes(
    media_id: str,
    threshold: float = Query(27.0, ge=1.0, le=100.0, description="PySceneDetect cut detection threshold"),
    refresh: bool = Query(False, description="Force fresh scene analysis and bypass cache"),
):
    manifest = media_service.get_media_manifest(media_id)
    if not manifest or not Path(manifest.storage_path).is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Media source '{media_id}' not found")
    from app.engine.scene_detector import detect_scenes
    try:
        scenes = detect_scenes(manifest.storage_path, threshold=threshold, force_refresh=refresh)
        return {
            "media_id": media_id,
            "scene_count": len(scenes),
            "scenes": scenes,
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Scene detection failed: {exc}")


@router.get("/media/{media_id}/thumbnail")
def get_media_thumbnail(
    media_id: str,
    time: float = Query(1.0, ge=0.0, description="Timestamp in seconds for poster frame"),
):
    manifest = media_service.get_media_manifest(media_id)
    if not manifest or not Path(manifest.storage_path).is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Media source '{media_id}' not found")
    from app.engine.thumbnail_generator import generate_thumbnail
    try:
        thumb_path = generate_thumbnail(manifest.storage_path, timestamp_s=time)
        return FileResponse(str(thumb_path), media_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Thumbnail generation failed: {exc}")


# 3. Transcript Upload, Retrieval & Generation
# 3. Transcript Upload, Retrieval, Correction & Generation
@router.post("/transcript/{media_id}/upload", response_model=Dict[str, Any])
async def upload_transcript(
    media_id: str,
    file: UploadFile = File(...),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    manifest = media_service.get_media_manifest(media_id)
    if not manifest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Media '{media_id}' not found")

    content_bytes = await file.read()
    upload_payload = {
        "media_id": media_id,
        "filename": file.filename,
        "sha256": hashlib.sha256(content_bytes).hexdigest(),
    }
    cached = handle_idempotency_check(idempotency_key, upload_payload)
    if cached:
        return cached
    content_str = content_bytes.decode("utf-8", errors="replace")

    fname = (file.filename or "").lower()
    transcript: Optional[Transcript] = None

    if fname.endswith(".srt") or fname.endswith(".vtt") or "-->" in content_str:
        try:
            from app.transcription.srt_vtt import parse_srt_or_vtt_to_transcript
            transcript = parse_srt_or_vtt_to_transcript(content_str, provenance=f"upload_{fname or 'subtitles'}")
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Failed to parse subtitle file: {str(e)}")
    else:
        try:
            raw_json = json.loads(content_str)
            adapter = FixtureTranscriptionAdapter(raw_json)
            transcript = adapter.transcribe(manifest.storage_path)
        except json.JSONDecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transcript file must be valid JSON, SRT, or WebVTT format")
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid transcript: {str(e)}")

    if transcript:
        timeline = timeline_service.get_timeline(media_id)
        if timeline:
            timeline.transcript = transcript
            timeline_service.save_timeline(timeline)

    resp_data = {
        "media_id": media_id,
        "word_count": len(transcript.words) if transcript else 0,
        "language": getattr(transcript, "language", "en"),
        "status": "uploaded",
    }
    save_idempotency_record(idempotency_key, upload_payload, 200, resp_data)
    return resp_data


@router.get("/transcript/{media_id}", response_model=Transcript)
def get_transcript(media_id: str):
    timeline = timeline_service.get_timeline(media_id)
    if not timeline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")
    return timeline.transcript


@router.get("/transcript/{media_id}/export")
def export_transcript(
    media_id: str,
    format: str = Query("txt", pattern="^(txt|json|srt|vtt)$", description="Export format: txt, json, srt, vtt"),
):
    timeline = timeline_service.get_timeline(media_id)
    if not timeline or not timeline.transcript:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")

    t = timeline.transcript
    if format == "json":
        return JSONResponse(content=t.model_dump())
    elif format == "srt":
        return Response(content=t.to_srt(), media_type="application/x-subrip", headers={"Content-Disposition": f"attachment; filename=transcript_{media_id}.srt"})
    elif format == "vtt":
        return Response(content=t.to_vtt(), media_type="text/vtt", headers={"Content-Disposition": f"attachment; filename=transcript_{media_id}.vtt"})
    else:
        return Response(content=t.to_txt(), media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=transcript_{media_id}.txt"})


@router.post("/transcript/{media_id}/edit_word")
def edit_transcript_word(media_id: str, payload: EditWordRequest):
    timeline = timeline_service.get_timeline(media_id)
    if not timeline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")

    updated = timeline.transcript.edit_word(
        word_id=payload.word_id,
        new_text=payload.new_text,
        new_start=payload.new_start,
        new_end=payload.new_end,
        new_speaker=payload.new_speaker,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Word ID '{payload.word_id}' not found")

    timeline_service.save_timeline(timeline)
    return {"status": "updated", "word": updated.model_dump()}


@router.delete("/transcript/{media_id}/word/{word_id}")
def delete_transcript_word(media_id: str, word_id: str):
    timeline = timeline_service.get_timeline(media_id)
    if not timeline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")

    deleted = timeline.transcript.delete_word(word_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Word ID '{word_id}' not found")

    timeline_service.save_timeline(timeline)
    return {"status": "deleted", "word_id": word_id, "remaining_words": len(timeline.transcript.words)}


@router.get("/transcript/{media_id}/search")
def search_transcript(media_id: str, q: str = Query(..., min_length=1)):
    timeline = timeline_service.get_timeline(media_id)
    if not timeline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")

    matches = timeline.transcript.search_words(q)
    return {
        "query": q,
        "match_count": len(matches),
        "matches": [w.model_dump() for w in matches],
    }


@router.get("/transcript/{media_id}/flagged")
def get_flagged_transcript_words(media_id: str, threshold: float = Query(0.5, ge=0.0, le=1.0)):
    timeline = timeline_service.get_timeline(media_id)
    if not timeline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")

    flagged = timeline.transcript.flagged_words(threshold=threshold)
    return {
        "media_id": media_id,
        "threshold": threshold,
        "flagged_count": len(flagged),
        "words": [w.model_dump() for w in flagged],
    }


@router.get("/transcript/{media_id}/audio_info")
def get_audio_info(media_id: str):
    manifest = media_service.get_media_manifest(media_id)
    if not manifest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Media '{media_id}' not found")

    from app.transcription.unified_transcriber import unified_transcriber
    info = unified_transcriber.inspect_audio(manifest.storage_path)
    return info


@router.post("/transcript/{media_id}/load_sample")
def load_sample_transcript(media_id: str):
    manifest = media_service.get_media_manifest(media_id)
    if not manifest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Media '{media_id}' not found")
    sample_file = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "sample_transcript.json"
    if not sample_file.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sample transcript fixture not found on server")
    with open(sample_file, "r", encoding="utf-8") as f:
        raw_json = json.load(f)
    adapter = FixtureTranscriptionAdapter(raw_json)
    transcript = adapter.transcribe(manifest.storage_path)
    timeline = timeline_service.get_timeline(media_id)
    if timeline:
        timeline.transcript = transcript
        timeline_service.save_timeline(timeline)
    return {"media_id": media_id, "word_count": len(transcript.words), "status": "sample_loaded"}


# 3b. Voice-Over Document Ingestion & Synchronization (PDF, Word .docx, text)
@router.post("/voiceover/{media_id}/upload")
async def upload_voiceover_document(
    media_id: str,
    file: UploadFile = File(...),
    auto_align: bool = Query(True, description="Align voice-over script words with video audio timing"),
    auto_captions: bool = Query(True, description="Generate synchronized captions on timeline"),
    synthesize_audio: bool = Query(False, description="Synthesize spoken TTS audio track"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    content = await file.read()
    request_payload = {
        "media_id": media_id,
        "filename": file.filename,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "auto_align": auto_align,
        "auto_captions": auto_captions,
        "synthesize_audio": synthesize_audio,
    }
    cached = handle_idempotency_check(idempotency_key, request_payload)
    if cached:
        return cached
    try:
        from app.services.voiceover_service import voiceover_service
        result = voiceover_service.process_voiceover_document(
            media_id=media_id,
            file_obj=content,
            filename=file.filename,
            auto_align=auto_align,
            auto_captions=auto_captions,
            synthesize_audio=synthesize_audio,
        )
        save_idempotency_record(idempotency_key, request_payload, 200, result)
        return result
    except Exception as e:
        if idempotency_key:
            idempotency_store.delete(idempotency_key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/transcript/{media_id}/generate")
def generate_transcript(
    media_id: str,
    language: Optional[str] = Query("auto", description="Transcription language: auto, en, ta, or language code"),
    model_size: Optional[str] = Query(None, description="Whisper model size: tiny, base, small, medium (defaults to WHISPER_MODEL_SIZE)"),
    vad_filter: bool = Query(True, description="Enable Voice Activity Detection filtering"),
):
    manifest = media_service.get_media_manifest(media_id)
    if not manifest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Media '{media_id}' not found")

    from app.transcription.unified_transcriber import unified_transcriber
    available, msg = unified_transcriber.is_available()
    if not available:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Transcription model unavailable: {msg}",
        )

    def _do_transcribe():
        transcript = unified_transcriber.transcribe(
            manifest.storage_path,
            language=language,
            model_size=model_size,
            vad_filter=vad_filter,
        )
        timeline = timeline_service.get_timeline(media_id)
        if timeline:
            timeline.transcript = transcript
            timeline_service.save_timeline(timeline)
        return {
            "word_count": len(transcript.words),
            "language": transcript.language,
            "words": [w.model_dump() for w in transcript.words],
        }

    job_id = job_manager.submit_job("transcription", _do_transcribe)
    return {"job_id": job_id, "status": "queued", "message": "Transcription job started"}


@router.get("/transcript/status/{job_id}")
def get_transcript_job_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")
    return job



# 4. Timeline Retrieval & Validation
@router.get("/timeline/{media_id}")
def get_timeline(media_id: str):
    tl = timeline_service.get_timeline(media_id)
    if not tl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")
    timeline_data = tl.model_dump()
    # Compatibility view used by the multi-track storyboard clients. Keep the
    # canonical `segments` field while exposing the same items as `clips`.
    timeline_data["output_duration_s"] = round(tl.total_output_duration, 4)
    timeline_data["clips"] = [
        {
            **segment.model_dump(),
            "source_start_s": segment.source_start,
            "source_end_s": segment.source_end,
            "output_duration_s": segment.output_duration,
        }
        for segment in tl.segments
    ]
    timeline_data["revision_history"] = [
        {
            "revision": operation.resulting_revision,
            "description": f"{operation.operation_type.value.replace('_', ' ').title()}",
            "operation_id": operation.operation_id,
        }
        for operation in tl.history
    ]
    return timeline_data


@router.get("/timeline/{media_id}/export/otio")
def export_timeline_otio(media_id: str):
    """Export the current source-linked timeline as OpenTimelineIO JSON."""
    timeline = timeline_service.get_timeline(media_id)
    manifest = media_service.get_media_manifest(media_id)
    if not timeline or not manifest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline or media '{media_id}' not found")
    source_path = Path(manifest.storage_path)
    if not source_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Original source media is unavailable")
    document = timeline_to_otio(timeline, str(source_path))
    return Response(
        content=json.dumps(document, ensure_ascii=False, separators=(",", ":")),
        media_type="application/vnd.opentimelineio+json",
        headers={"Content-Disposition": f'attachment; filename="{media_id}.otio"'},
    )


@router.get("/timeline/{media_id}/suggestions")
def get_timeline_suggestions(media_id: str, topic: Optional[str] = Query(None)):
    timeline = timeline_service.get_timeline(media_id)
    if not timeline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")
    manifest = media_service.get_media_manifest(media_id)
    media_path = manifest.storage_path if manifest else None
    from app.services.smart_suggestions import smart_suggestion_service
    suggestions = smart_suggestion_service.analyze_timeline(timeline, topic=topic, media_path=media_path)
    return {
        "media_id": media_id,
        "count": len(suggestions),
        "suggestions": suggestions,
    }



@router.post("/timeline/{media_id}/validate")
def validate_timeline_endpoint(media_id: str):
    engine = timeline_service.get_engine(media_id)
    if not engine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")
    try:
        engine.validate_timeline(engine.timeline)
        return {"valid": True, "revision": engine.timeline.revision, "duration_s": engine.timeline.total_output_duration}
    except Exception as e:
        return {"valid": False, "error": str(e)}


class ReorderTimelineRequest(BaseModel):
    segment_ids: List[str]


@router.post("/timeline/{media_id}/reorder")
def reorder_timeline_segments(media_id: str, payload: ReorderTimelineRequest):
    engine = timeline_service.get_engine(media_id)
    if not engine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")
    try:
        operation = engine.apply_reorder(payload.segment_ids, provenance="timeline_drag")
        timeline_service.save_timeline(engine.timeline)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "status": "applied",
        "revision": engine.timeline.revision,
        "duration_s": round(engine.timeline.total_output_duration, 4),
        "operation_id": operation.operation_id,
        "timeline_hash": compute_timeline_hash(engine.timeline.model_dump()),
    }


class SplitTimelineRequest(BaseModel):
    split_time: float = Field(..., description="Timeline output timestamp in seconds where clip should be sliced")


@router.post("/timeline/{media_id}/split")
def split_timeline_clip(media_id: str, payload: SplitTimelineRequest):
    engine = timeline_service.get_engine(media_id)
    if not engine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")
    try:
        op = engine.apply_split_clip(split_time=payload.split_time, provenance="timeline_editor")
        timeline_service.save_timeline(engine.timeline)
        return {
            "status": "applied",
            "operation_id": op.operation_id,
            "revision": engine.timeline.revision,
            "segment_count": len(engine.timeline.video_track.segments),
            "duration_s": round(engine.timeline.total_output_duration, 4),
            "timeline_hash": compute_timeline_hash(engine.timeline.model_dump()),
            "message": f"Split clip at {payload.split_time:.2f}s",
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


class DuplicateTimelineRequest(BaseModel):
    segment_id: Optional[str] = Field(None, description="ID of specific segment to duplicate")
    segment_index: Optional[int] = Field(None, description="Index of segment to duplicate (default: last)")


@router.post("/timeline/{media_id}/duplicate")
def duplicate_timeline_clip(media_id: str, payload: DuplicateTimelineRequest):
    engine = timeline_service.get_engine(media_id)
    if not engine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")
    try:
        op = engine.apply_duplicate_clip(
            segment_id=payload.segment_id,
            segment_index=payload.segment_index,
            provenance="timeline_editor",
        )
        timeline_service.save_timeline(engine.timeline)
        return {
            "status": "applied",
            "operation_id": op.operation_id,
            "revision": engine.timeline.revision,
            "segment_count": len(engine.timeline.video_track.segments),
            "duration_s": round(engine.timeline.total_output_duration, 4),
            "timeline_hash": compute_timeline_hash(engine.timeline.model_dump()),
            "message": "Duplicated timeline clip.",
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# 5. Instructions & Clarifications
@router.post("/instruction/{media_id}", response_model=InstructionResult)
def submit_instruction(
    media_id: str,
    payload: InstructionRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    cached = handle_idempotency_check(idempotency_key, {"media_id": media_id, "instruction": payload.instruction})
    if cached:
        return cached

    if settings.INSTRUCTION_PROVIDER.strip().lower() in {"auto", "ollama"}:
        # Route natural-language requests through the configured local AI
        # planner as well as the reviewed-plan UI. The old direct API always
        # used keyword regexes, which made the same prompt behave differently
        # depending on which UI control submitted it.
        engine = timeline_service.get_engine(media_id)
        if not engine:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")
        before_summary = engine.timeline.summary()
        before_history_length = len(engine.timeline.history)
        try:
            plan = plan_service.generate_plan(media_id, payload.instruction)
        except OllamaProviderError as exc:
            result = InstructionResult(
                request_id=f"req_{uuid.uuid4().hex[:10]}",
                status=InstructionStatus.REJECTED,
                message=str(exc),
                error_code="AI_PLANNER_UNAVAILABLE",
                before_summary=before_summary,
                timeline_revision=engine.timeline.revision,
                duration_s=engine.timeline.total_output_duration,
            )
        else:
            clarification = next((op for op in plan["operations"] if op.get("type") == "needs_clarification"), None)
            if clarification:
                result = InstructionResult(
                    request_id=f"req_{uuid.uuid4().hex[:10]}",
                    status=InstructionStatus.NEEDS_CLARIFICATION,
                    message=clarification.get("description") or "Please clarify this editing request.",
                    clarification_question=clarification.get("description"),
                    before_summary=before_summary,
                    timeline_revision=engine.timeline.revision,
                    duration_s=engine.timeline.total_output_duration,
                )
            else:
                applied = plan_service.apply_plan(media_id, plan["operations"])
                new_operations = engine.timeline.history[before_history_length:]
                succeeded = applied.get("status") in {"applied", "partial"} and applied.get("applied_count", 0) > 0
                message = (
                    f"Applied {applied['applied_count']} planned edit(s)."
                    if succeeded else
                    (applied.get("errors") or applied.get("skipped_operations") or ["No supported edit could be applied."])[0]
                )
                result = InstructionResult(
                    request_id=f"req_{uuid.uuid4().hex[:10]}",
                    status=InstructionStatus.APPLIED if succeeded else InstructionStatus.REJECTED,
                    message=message,
                    operations=new_operations,
                    before_summary=before_summary,
                    after_summary=engine.timeline.summary(),
                    warnings=(
                        ([plan["provider_notice"]] if plan.get("provider_notice") else [])
                        + applied.get("skipped_operations", [])
                        + applied.get("errors", [])
                    ),
                    timeline_hash=compute_timeline_hash(engine.timeline.model_dump()),
                    timeline_revision=engine.timeline.revision,
                    duration_s=engine.timeline.total_output_duration,
                    operation_id=new_operations[-1].operation_id if new_operations else None,
                    error_code=None if succeeded else "UNSUPPORTED_OR_INVALID_INSTRUCTION",
                )
    else:
        result = instruction_service.process_instruction(media_id, payload.instruction)
    if result.time_policy is None and (basis := requested_time_basis(payload.instruction)):
        result.time_policy = time_policy_statement(basis)
        if result.time_policy not in result.message:
            result.message = f"{result.message} {result.time_policy}".strip()
    res_dict = result.model_dump()
    save_idempotency_record(idempotency_key, {"media_id": media_id, "instruction": payload.instruction}, 200, res_dict)
    return result


@router.post("/instruction/clarify", response_model=InstructionResult)
def submit_clarification_choice(
    payload: ClarificationAnswerRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    cached = handle_idempotency_check(idempotency_key, payload.model_dump())
    if cached:
        return cached

    result = instruction_service.resolve_clarification(payload.session_id, payload.selected_option_id)
    res_dict = result.model_dump()
    save_idempotency_record(idempotency_key, payload.model_dump(), 200, res_dict)
    return result


# 6. Operations & History
@router.get("/timeline/{media_id}/history")
def get_timeline_history(media_id: str):
    tl = timeline_service.get_timeline(media_id)
    if not tl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")
    return {
        "media_id": media_id,
        "revision": tl.revision,
        "history": [op.model_dump() for op in tl.history],
    }


@router.post("/timeline/{media_id}/undo", response_model=InstructionResult)
def undo_timeline_edit(
    media_id: str,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    return submit_instruction(media_id, InstructionRequest(instruction="undo"), idempotency_key=idempotency_key)


@router.post("/timeline/{media_id}/redo", response_model=InstructionResult)
def redo_timeline_edit(
    media_id: str,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    return submit_instruction(media_id, InstructionRequest(instruction="redo"), idempotency_key=idempotency_key)


@router.post("/timeline/{media_id}/restore", response_model=InstructionResult)
def restore_timeline_edit(
    media_id: str,
    payload: RestoreRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    instr = f"restore {payload.target_operation_id}" if payload.target_operation_id else f"restore revision {payload.target_revision}"
    return submit_instruction(media_id, InstructionRequest(instruction=instr), idempotency_key=idempotency_key)


# 7. Rendering & Download
@router.post("/render/{media_id}", response_model=RenderJobResponse)
def trigger_render(
    media_id: str,
    payload: Optional[RenderOptions] = None,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    render_options = (payload or RenderOptions()).model_dump()
    cached = handle_idempotency_check(idempotency_key, {"media_id": media_id, "options": render_options})
    if cached:
        return cached

    try:
        job_id = render_service.start_render_job(media_id, render_options)
        resp = RenderJobResponse(job_id=job_id, status=JobStatus.QUEUED, message="Render job queued successfully")
        save_idempotency_record(idempotency_key, {"media_id": media_id, "options": render_options}, 200, resp.model_dump())
        return resp
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/render/status/{job_id}")
def get_render_job_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Render job '{job_id}' not found")
    return job


@router.post("/render/cancel/{job_id}")
def cancel_render_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job or job.get("job_type") != "render":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Render job '{job_id}' not found")
    cancelled = job_manager.cancel_job(job_id)
    return cancelled


@router.get("/render/manifest/{filename}", response_model=RenderManifest)
def get_render_manifest(filename: str):
    manifest = render_service.get_render_manifest_by_filename(filename)
    if not manifest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Render manifest for '{filename}' not found")
    return manifest


@router.get("/render/download/{filename}")
def download_rendered_video(filename: str):
    file_path = Path(settings.RENDER_OUTPUT_DIR) / filename
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File '{filename}' not found")
    return FileResponse(path=str(file_path.resolve()), filename=filename, media_type="video/mp4")


@router.get("/renders/{job_id}/download")
def download_render_job(job_id: str):
    """Download the verified output for a completed render job."""
    job = job_manager.get_job(job_id)
    if not job or job.get("job_type") != "render":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Render job '{job_id}' not found")
    if job.get("status") != JobStatus.COMPLETED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Render output is not ready for download")
    result = job.get("result") or {}
    output_path = result.get("output_path") if isinstance(result, dict) else None
    if not output_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Completed render has no output file")
    render_root = Path(settings.RENDER_OUTPUT_DIR).resolve()
    target = Path(output_path).resolve()
    try:
        target.relative_to(render_root)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Render output path is outside the configured render folder")
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Render output file is no longer available")
    return FileResponse(path=str(target), filename=target.name, media_type="video/mp4")


# 8. Session Execution Endpoint
@router.post("/session/execute")
def run_session_endpoint(payload: SessionRunRequest):
    try:
        res = execute_session(payload.session_data, output_results_path=None)
        return res
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# 9. Project Management & Persistence
class CreateProjectPayload(BaseModel):
    name: str = "Untitled Project"
    media_id: Optional[str] = None
    description: Optional[str] = None


@router.post("/projects")
def create_project_endpoint(payload: CreateProjectPayload):
    proj = project_service.create_project(name=payload.name, media_id=payload.media_id, description=payload.description)
    res = dict(proj)
    res["id"] = proj["project_id"]
    return res


@router.get("/projects")
def list_projects_endpoint():
    projs = project_service.list_projects()
    res = []
    for p in projs:
        d = dict(p)
        d["id"] = p["project_id"]
        res.append(d)
    return res


@router.get("/projects/{project_id}")
def get_project_endpoint(project_id: str):
    proj = project_service.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found")
    res = dict(proj)
    res["id"] = proj["project_id"]
    return res


class UpdateProjectPayload(BaseModel):
    name: Optional[str] = None
    media_id: Optional[str] = None
    description: Optional[str] = None


@router.patch("/projects/{project_id}")
def update_project_endpoint(project_id: str, payload: UpdateProjectPayload):
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        updates["name"] = (updates["name"] or "").strip()
        if not updates["name"]:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Project name cannot be empty")
    if updates.get("media_id") and not media_service.get_media_manifest(updates["media_id"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Media '{updates['media_id']}' not found")
    project = project_service.update_project(project_id, updates)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found")
    return {**project, "id": project["project_id"]}


@router.post("/projects/{project_id}/duplicate")
def duplicate_project_endpoint(project_id: str):
    project = project_service.duplicate_project(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found")
    return {**project, "id": project["project_id"]}


@router.delete("/projects/{project_id}")
def delete_project_endpoint(project_id: str):
    if not project_service.delete_project(project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found")
    return {"status": "deleted", "project_id": project_id}


# 10. Bundled Demo Loader
@router.post("/demo/load")
def load_bundled_demo():
    fixtures_dir = Path(__file__).parent.parent.parent / "tests" / "fixtures"
    video_path = fixtures_dir / "sample_with_audio.mp4"
    transcript_path = fixtures_dir / "sample_transcript.json"

    if not video_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo video fixture not found")

    with open(video_path, "rb") as vf:
        manifest = media_service.intake_uploaded_file(vf, "demo_travel_reel.mp4")

    # Load transcript
    transcript = Transcript()
    if transcript_path.is_file():
        with open(transcript_path, "r", encoding="utf-8") as tf:
            raw_json = json.load(tf)
        adapter = FixtureTranscriptionAdapter(raw_json)
        transcript = adapter.transcribe(manifest.storage_path)

    timeline_service.initialize_timeline(manifest, transcript)
    proj = project_service.create_project("Explore Demo Reel", media_id=manifest.media_id, description="Bundled IncuBrix 2027 Sample Project")

    engine = timeline_service.get_engine(manifest.media_id)
    tl_dict = engine.timeline.model_dump() if engine else {}

    return {
        "status": "loaded",
        "media_id": manifest.media_id,
        "project": {**proj, "id": proj["project_id"]},
        "media": manifest.model_dump(),
        "manifest": manifest.model_dump(),
        "timeline": tl_dict,
        "transcript_words": len(transcript.words),
    }


# 11. AI Edit Plan Interpretation & Review
class GeneratePlanPayload(BaseModel):
    prompt: Optional[str] = None
    instruction: Optional[str] = None


class ApplyPlanPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    operations: Optional[List[Dict[str, Any]]] = None


@router.post("/plan/generate/{media_id}")
def generate_ai_edit_plan(media_id: str, payload: GeneratePlanPayload):
    prompt = payload.prompt or payload.instruction or ""
    try:
        plan = plan_service.generate_plan(media_id=media_id, prompt=prompt)
        return plan
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/plan/apply/{media_id}")
def apply_ai_edit_plan(media_id: str, payload: ApplyPlanPayload):
    ops = payload.operations or []
    try:
        result = plan_service.apply_plan(media_id=media_id, operations=ops)
        engine = timeline_service.get_engine(media_id)
        thash = compute_timeline_hash(engine.timeline.model_dump()) if engine else ""
        result_status = result.get("status", "rejected")
        applied_count = result.get("applied_count", len(ops))
        skipped = result.get("skipped_operations", [])
        if result_status == "applied":
            message = f"Applied {applied_count} edit operations."
        elif result_status == "partial":
            message = f"Applied {applied_count} supported edit(s). Skipped {len(skipped)} unsupported or unclear part(s)."
        elif result_status == "unsupported":
            message = "No requested edits could be applied because the plan has no supported operations. See skipped_operations for details."
        else:
            message = "The plan encountered an execution error. No timeline changes were kept."
        return {
            **result,
            "status": result_status,
            "timeline_hash": thash,
            "message": message,
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# 12. Direct Title Card & Audio Finishing Endpoints
class CaptionStylePayload(BaseModel):
    font_family: str = Field(default="Arial", min_length=1, max_length=100)
    font_size: int = Field(default=24, ge=8, le=120)
    text_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: int = Field(default=2, ge=0, le=20)
    shadow_offset: int = Field(default=1, ge=0, le=20)
    background_box: bool = False
    background_color: str = "#000000"
    vertical_position: str = "bottom"

    @field_validator("vertical_position")
    @classmethod
    def validate_vertical_position(cls, value: str) -> str:
        value = value.strip().lower()
        if value == "middle":
            value = "center"
        if value not in {"top", "center", "bottom"}:
            raise ValueError("vertical_position must be top, center, or bottom")
        return value

    @field_validator("text_color", "outline_color", "background_color")
    @classmethod
    def validate_color(cls, value: str) -> str:
        clean = value.strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", clean):
            raise ValueError("Colors must use #RRGGBB format")
        return clean


def _hex_color_to_ass(color: str) -> str:
    """Convert HTML #RRGGBB to opaque ASS &HAABBGGRR color format."""
    red, green, blue = color[1:3], color[3:5], color[5:7]
    return f"&H00{blue}{green}{red}".upper()


@router.post("/caption-style/{media_id}")
def update_caption_style(media_id: str, payload: CaptionStylePayload):
    engine = timeline_service.get_engine(media_id)
    if not engine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")

    style = {
        "font_name": payload.font_family.strip(),
        "font_size": payload.font_size,
        "primary_color": _hex_color_to_ass(payload.text_color),
        "outline_color": _hex_color_to_ass(payload.outline_color),
        "outline_width": payload.outline_width,
        "shadow_offset": payload.shadow_offset,
        "back_color": _hex_color_to_ass(payload.background_color),
        "border_style": 3 if payload.background_box else 1,
        "position": payload.vertical_position,
        "alignment": {"bottom": 2, "top": 8, "center": 5}[payload.vertical_position],
    }
    try:
        operation = engine.apply_caption_style(style, apply_to_existing=True, provenance="caption_style_studio")
        timeline_service.save_timeline(engine.timeline)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not update caption style: {exc}") from exc

    return {
        "status": "applied",
        "revision": engine.timeline.revision,
        "style": engine.timeline.global_caption_style.model_dump(),
        "operation_id": operation.operation_id,
        "timeline_hash": compute_timeline_hash(engine.timeline.model_dump()),
    }


class TitleCardPayload(BaseModel):
    text: str
    position: str = "center"
    timing: Optional[str] = None
    duration_s: Optional[float] = None
    duration_seconds: float = 3.5


@router.post("/timeline/{media_id}/title")
def add_title_card(media_id: str, payload: TitleCardPayload):
    engine = timeline_service.get_engine(media_id)
    if not engine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")

    media_dur = engine.timeline.total_output_duration
    dur = payload.duration_s or payload.duration_seconds
    timing = payload.timing or "opening"

    if timing == "closing":
        st = max(0.0, media_dur - dur)
        et = media_dur
    else:
        st = 0.0
        et = min(dur, media_dur)

    overlay = engine.apply_add_text_overlay(
        text=payload.text,
        position=payload.position,
        source_start=st,
        source_end=et,
    )
    timeline_service.save_timeline(engine.timeline)
    return {
        "status": "applied",
        "overlay": overlay.model_dump(),
        "revision": engine.timeline.revision,
        "timeline_hash": compute_timeline_hash(engine.timeline.model_dump()),
        "message": f"Added title overlay '{payload.text}'",
    }


class BackgroundMusicPayload(BaseModel):
    enabled: bool = True
    volume: float = 0.2
    ducking: Optional[bool] = None
    ducking_enabled: bool = True


@router.post("/timeline/{media_id}/bgm")
def configure_background_music(media_id: str, payload: BackgroundMusicPayload):
    engine = timeline_service.get_engine(media_id)
    if not engine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Timeline for media '{media_id}' not found")

    is_ducking = payload.ducking if payload.ducking is not None else payload.ducking_enabled

    if payload.enabled:
        engine.timeline.background_music = BackgroundMusic(
            track_id="default_bgm",
            volume=payload.volume,
            ducking_enabled=is_ducking,
        )
    else:
        engine.timeline.background_music = None

    timeline_service.save_timeline(engine.timeline)
    return {
        "status": "applied",
        "has_bgm": engine.timeline.background_music is not None,
        "volume": payload.volume if payload.enabled else 0.0,
        "ducking": is_ducking if payload.enabled else False,
        "timeline_hash": compute_timeline_hash(engine.timeline.model_dump()),
        "message": "Background music configured.",
    }

