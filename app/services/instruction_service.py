import json
import uuid
from typing import Any, Dict, List, Optional
from app.config import settings
from app.engine.canonical_hash import compute_timeline_hash
from app.engine.instruction_parser import ClarificationNeeded, InstructionParser
from app.engine.snapping import adjust_cut_boundary
from app.engine.time_policy import requested_time_basis, time_policy_statement
from app.models.db import ClarificationSessionRecord, SessionLocal
from app.models.operation import (
    ClarificationOption,
    CommittedOperation,
    InstructionResult,
    InstructionStatus,
    OperationProposal,
    OperationType,
)
from app.models.timeline import Timeline
from app.models.transcript import normalize_text
from app.services.media_service import media_service
from app.services.timeline_service import timeline_service


class InstructionService:
    def __init__(self):
        self.parser = InstructionParser()

    def process_instruction(
        self,
        media_id: str,
        instruction_text: str,
        request_id: Optional[str] = None,
    ) -> InstructionResult:
        req_id = request_id or f"req_{uuid.uuid4().hex[:10]}"
        engine = timeline_service.get_engine(media_id)
        if not engine:
            return InstructionResult(
                request_id=req_id,
                status=InstructionStatus.REJECTED,
                message=f"No timeline found for media ID '{media_id}'",
                error_code="TIMELINE_NOT_FOUND",
            )

        before_summary = engine.timeline.summary()
        manifest = media_service.get_media_manifest(media_id)
        media_path = manifest.storage_path if manifest else None

        # 1. Parse instruction and detect potential ambiguity
        try:
            proposal = self.parser.parse_instruction(instruction_text, engine.timeline)
        except ClarificationNeeded as e:
            # Store clarification session for resolution
            session_id = f"clar_{uuid.uuid4().hex[:8]}"
            db = SessionLocal()
            try:
                rec = ClarificationSessionRecord(
                    session_id=session_id,
                    media_id=media_id,
                    question=e.question,
                    options_json=json.dumps([opt.model_dump() for opt in e.options]),
                    pending_proposal_json=json.dumps({
                        "instruction_text": instruction_text,
                        "request_id": req_id,
                    }),
                )
                db.add(rec)
                db.commit()
            finally:
                db.close()

            return InstructionResult(
                request_id=req_id,
                status=InstructionStatus.NEEDS_CLARIFICATION,
                message="Instruction is ambiguous across multiple occurrences in transcript. Clarification required.",
                clarification_question=e.question,
                options=e.options,
                operation_id=session_id,
                before_summary=before_summary,
                timeline_revision=engine.timeline.revision,
                duration_s=engine.timeline.total_output_duration,
            )
        except Exception as e:
            # Parse or semantic rejection
            rejected_time_basis = requested_time_basis(instruction_text)
            time_policy = time_policy_statement(rejected_time_basis) if rejected_time_basis else None
            return InstructionResult(
                request_id=req_id,
                status=InstructionStatus.REJECTED,
                message=str(e) + (f" {time_policy}" if time_policy else ""),
                error_code="INVALID_INSTRUCTION",
                before_summary=before_summary,
                timeline_revision=engine.timeline.revision,
                duration_s=engine.timeline.total_output_duration,
                time_policy=time_policy,
            )

        # 2. Execute operation proposal atomically
        return self._execute_proposal(engine, proposal, req_id, media_path, before_summary)

    def process_proposal(
        self,
        media_id: str,
        proposal: OperationProposal,
        request_id: Optional[str] = None,
    ) -> InstructionResult:
        """Execute a validated typed proposal without converting it back to text."""
        req_id = request_id or f"req_{uuid.uuid4().hex[:10]}"
        engine = timeline_service.get_engine(media_id)
        if not engine:
            return InstructionResult(
                request_id=req_id,
                status=InstructionStatus.REJECTED,
                message=f"No timeline found for media ID '{media_id}'",
                error_code="TIMELINE_NOT_FOUND",
            )
        before_summary = engine.timeline.summary()
        manifest = media_service.get_media_manifest(media_id)
        media_path = manifest.storage_path if manifest else None
        self._resolve_typed_transcript_targets(proposal, engine.timeline)
        return self._execute_proposal(engine, proposal, req_id, media_path, before_summary)

    @staticmethod
    def _resolve_typed_transcript_targets(proposal: OperationProposal, timeline: Timeline) -> None:
        """Resolve AI-provided phrase text to stable transcript words deterministically."""
        op_type = proposal.operation_type
        params = proposal.parameters
        if op_type not in (OperationType.REMOVE_PHRASE, OperationType.MUTE, OperationType.BLEEP, OperationType.ADD_CAPTION):
            return
        if op_type == OperationType.ADD_CAPTION and params.get("anchor_word_ids"):
            return
        word_ids = params.get("word_ids") or params.get("anchor_word_ids") or []
        if not word_ids and op_type == OperationType.REMOVE_PHRASE and params.get("target_words"):
            word_ids = [w.id if hasattr(w, "id") else w.get("id") for w in params["target_words"]]
        words = [timeline.transcript.get_word_by_id(str(word_id)) for word_id in word_ids]
        words = [word for word in words if word is not None]
        if not words:
            phrase = params.get("anchor_phrase") or params.get("phrase")
            if op_type in (OperationType.MUTE, OperationType.BLEEP):
                phrase = phrase or params.get("text") or params.get("word")
            if phrase:
                target_tokens = [normalize_text(token) for token in str(phrase).split()]
                target_tokens = [token for token in target_tokens if token]
                transcript = timeline.transcript.words
                occurrences = []
                for start in range(0, len(transcript) - len(target_tokens) + 1):
                    candidate = transcript[start:start + len(target_tokens)]
                    if [word.normalized_text or normalize_text(word.text) for word in candidate] == target_tokens:
                        occurrences.append(candidate)
                if len(occurrences) > 1:
                    raise ValueError(f"The transcript phrase '{phrase}' occurs {len(occurrences)} times; specify which occurrence to edit.")
                if len(occurrences) == 1:
                    words = occurrences[0]
        if not words:
            if op_type in (OperationType.REMOVE_PHRASE, OperationType.ADD_CAPTION):
                raise ValueError("The requested phrase could not be matched to transcript word IDs; no change was applied.")
            # A timed mute/bleep may not refer to transcript speech.
            if params.get("start") is not None and params.get("end") is not None:
                return
            raise ValueError("A transcript phrase or valid time range is required for this operation.")
        ids = [word.id for word in words]
        params["word_ids"] = ids
        params["start"] = min(word.start for word in words)
        params["end"] = max(word.end for word in words)
        if op_type == OperationType.REMOVE_PHRASE:
            params["target_words"] = words
        elif op_type == OperationType.ADD_CAPTION:
            params["anchor_word_ids"] = ids

    def resolve_clarification(
        self,
        session_id: str,
        selected_option_id: str,
        request_id: Optional[str] = None,
    ) -> InstructionResult:
        req_id = request_id or f"req_{uuid.uuid4().hex[:10]}"
        db = SessionLocal()
        clar_rec = None
        try:
            clar_rec = db.query(ClarificationSessionRecord).filter(ClarificationSessionRecord.session_id == session_id).first()
            if not clar_rec:
                return InstructionResult(
                    request_id=req_id,
                    status=InstructionStatus.REJECTED,
                    message=f"Clarification session '{session_id}' not found or already expired",
                    error_code="INVALID_SESSION",
                )
            options_data = json.loads(clar_rec.options_json)
            media_id = clar_rec.media_id
        finally:
            db.close()

        # Match selected option ID (e.g., "opt_1", "1", or label match)
        clean_choice = selected_option_id.strip().lower()
        matched_opt = None
        for opt_dict in options_data:
            opt_id = opt_dict["id"].lower()
            idx_str = opt_id.replace("opt_", "")
            if clean_choice in (opt_id, idx_str, f"option {idx_str}", f"occurrence {idx_str}"):
                matched_opt = opt_dict
                break

        if not matched_opt:
            return InstructionResult(
                request_id=req_id,
                status=InstructionStatus.REJECTED,
                message=f"Selection '{selected_option_id}' does not match any valid clarification option.",
                error_code="INVALID_OPTION_SELECTION",
            )

        engine = timeline_service.get_engine(media_id)
        if not engine:
            return InstructionResult(
                request_id=req_id,
                status=InstructionStatus.REJECTED,
                message=f"No timeline found for media ID '{media_id}'",
                error_code="TIMELINE_NOT_FOUND",
            )

        before_summary = engine.timeline.summary()
        manifest = media_service.get_media_manifest(media_id)
        media_path = manifest.storage_path if manifest else None

        tdata = matched_opt["target_data"]
        op_type = OperationType(tdata["operation_type"])
        params = tdata["parameters"]
        # Inject chosen disambiguated parameters
        if "word_ids" in tdata:
            words = [engine.timeline.transcript.get_word_by_id(wid) for wid in tdata["word_ids"]]
            valid_words = [w for w in words if w]
            if op_type == OperationType.REMOVE_PHRASE:
                params["target_words"] = valid_words
            elif op_type in (OperationType.MUTE, OperationType.BLEEP):
                params["word_ids"] = tdata["word_ids"]
                params["start"] = tdata["start"]
                params["end"] = tdata["end"]
            elif op_type == OperationType.ADD_CAPTION:
                params["anchor_word_ids"] = tdata["word_ids"]

        proposal = OperationProposal(
            operation_type=op_type,
            parameters=params,
            provenance="clarification_resolution",
        )

        result = self._execute_proposal(engine, proposal, req_id, media_path, before_summary)

        # Cleanup clarification record
        db = SessionLocal()
        try:
            db.query(ClarificationSessionRecord).filter(ClarificationSessionRecord.session_id == session_id).delete()
            db.commit()
        finally:
            db.close()

        return result

    def _execute_proposal(
        self,
        engine,
        proposal: OperationProposal,
        req_id: str,
        media_path: Optional[str],
        before_summary: Dict[str, Any],
    ) -> InstructionResult:
        warnings: List[str] = []
        op_type = proposal.operation_type
        params = proposal.parameters
        if op_type == OperationType.BLEEP and params.get("word_ids"):
            low_confidence_words = [
                word for word_id in params["word_ids"]
                if (word := engine.timeline.transcript.get_word_by_id(str(word_id))) is not None
                and (
                    (word.confidence is not None and word.confidence < 0.5)
                    or bool(word.warnings)
                )
            ]
            if low_confidence_words:
                flagged = ", ".join(
                    f"'{word.text}' ({word.confidence:.2f})" if word.confidence is not None
                    else f"'{word.text}' (flagged)"
                    for word in low_confidence_words
                )
                warning = (
                    f"Bleep was not applied because transcript target(s) have low confidence: {flagged}. "
                    "Review or correct the transcript, then retry."
                )
                return InstructionResult(
                    request_id=req_id,
                    status=InstructionStatus.REJECTED,
                    message=warning,
                    before_summary=before_summary,
                    after_summary=before_summary,
                    warnings=[warning],
                    timeline_hash=compute_timeline_hash(engine.timeline.model_dump()),
                    timeline_revision=engine.timeline.revision,
                    duration_s=engine.timeline.total_output_duration,
                    error_code="LOW_CONFIDENCE_TRANSCRIPT_TARGET",
                )
        timed_range_operation = op_type in {
            OperationType.CUT_RANGE, OperationType.KEEP_RANGE, OperationType.SPEED_CHANGE,
            OperationType.MUTE, OperationType.BLEEP,
        }
        if timed_range_operation and "start" in params and "end" in params and not params.get("word_ids"):
            params.setdefault("time_basis", "current_timeline")
        time_policy = None
        if (
            timed_range_operation
            and "start" in params and "end" in params and not params.get("word_ids")
        ):
            time_policy = time_policy_statement(params.get("time_basis", "current_timeline"))

        try:
            committed_op: CommittedOperation
            resolved_cut_intervals = None

            # Audio-aware snapping for cuts if media_path exists
            if op_type == OperationType.CUT_RANGE and settings.AUDIO_SNAPPING_ENABLED and media_path:
                source_dur = engine.timeline.source_metadata.duration
                if params.get("time_basis") == "current_timeline":
                    resolved_cut_intervals = []
                    snap_details = []
                    for source_start, source_end in engine._source_intervals_for_output_range(params["start"], params["end"]):
                        snap_start = adjust_cut_boundary(
                            media_path, source_start, source_dur,
                            protected_words=engine.timeline.transcript.words,
                            window_ms=settings.SNAPPING_WINDOW_MS, boundary_role="start",
                        )
                        snap_end = adjust_cut_boundary(
                            media_path, source_end, source_dur,
                            protected_words=engine.timeline.transcript.words,
                            window_ms=settings.SNAPPING_WINDOW_MS, boundary_role="end",
                        )
                        resolved_cut_intervals.append((snap_start.adjusted_time, snap_end.adjusted_time))
                        snap_details.append({"start_snap": snap_start.to_dict(), "end_snap": snap_end.to_dict()})
                    params["snapping_metadata"] = {"source_intervals": snap_details}
                    if any(
                        item[side]["snapped"]
                        for item in snap_details for side in ("start_snap", "end_snap")
                    ):
                        warnings.append("Audio-aware cut snapping preserved transcript word boundaries; see snapping_metadata for adjusted source times.")
                else:
                    snap_start = adjust_cut_boundary(
                        media_path, params["start"], source_dur,
                        protected_words=engine.timeline.transcript.words,
                        window_ms=settings.SNAPPING_WINDOW_MS, boundary_role="start",
                    )
                    snap_end = adjust_cut_boundary(
                        media_path, params["end"], source_dur,
                        protected_words=engine.timeline.transcript.words,
                        window_ms=settings.SNAPPING_WINDOW_MS, boundary_role="end",
                    )
                    if snap_start.snapped or snap_end.snapped:
                        warnings.append(f"Audio-aware snapping adjusted cut from [{params['start']}, {params['end']}] to [{snap_start.adjusted_time}, {snap_end.adjusted_time}]")
                        params["start"] = snap_start.adjusted_time
                        params["end"] = snap_end.adjusted_time
                        params["snapping_metadata"] = {
                            "start_snap": snap_start.to_dict(),
                            "end_snap": snap_end.to_dict(),
                        }

            if op_type == OperationType.CUT_RANGE:
                committed_op = engine.apply_cut(
                    params["start"], params["end"],
                    time_basis=params.get("time_basis", "source"),
                    resolved_source_intervals=resolved_cut_intervals,
                )
            elif op_type == OperationType.KEEP_RANGE:
                committed_op = engine.apply_keep_range(params["start"], params["end"], time_basis=params.get("time_basis", "source"))
            elif op_type == OperationType.REMOVE_PHRASE:
                committed_op = engine.apply_remove_phrase(params["target_words"])
            elif op_type == OperationType.REORDER_SECTIONS:
                committed_op = engine.apply_reorder(params["new_segment_order"])
            elif op_type == OperationType.SPEED_CHANGE:
                committed_op = engine.apply_speed_change(params["start"], params["end"], params["speed"], time_basis=params.get("time_basis", "source"))
            elif op_type == OperationType.MUTE:
                committed_op = engine.apply_mute(params["start"], params["end"], word_ids=params.get("word_ids"), time_basis=params.get("time_basis", "source"))
            elif op_type == OperationType.BLEEP:
                committed_op = engine.apply_bleep(params["start"], params["end"], frequency_hz=params.get("frequency_hz", 1000.0), word_ids=params.get("word_ids"), time_basis=params.get("time_basis", "source"))
            elif op_type == OperationType.ADD_CAPTION:
                committed_op = engine.apply_add_caption(params["text"], params["anchor_word_ids"], anchor_phrase=params.get("anchor_phrase"))
            elif op_type == OperationType.ADD_TEXT_OVERLAY:
                committed_op = engine.apply_add_text_overlay(params["text"], position=params.get("position", "bottom"), source_start=params.get("source_start"), source_end=params.get("source_end"))
            elif op_type == OperationType.GENERATE_CAPTIONS:
                committed_op = engine.apply_generate_captions()
            elif op_type == OperationType.REMOVE_FILLER_WORDS:
                committed_op = engine.apply_remove_filler_words()
            elif op_type == OperationType.REMOVE_SILENCE:
                committed_op = engine.apply_remove_silence(params.get("threshold_seconds", 1.0))
            elif op_type == OperationType.ADD_BACKGROUND_MUSIC:
                committed_op = engine.apply_background_music(track_id=params.get("track_id", "default_bgm"), volume=params.get("volume", 0.2), ducking_enabled=params.get("ducking_enabled", True))
            elif op_type == OperationType.COLOR_GRADE:
                committed_op = engine.apply_color_grade(
                    preset=params.get("preset"),
                    brightness=params.get("brightness", 0.0),
                    contrast=params.get("contrast", 1.0),
                    saturation=params.get("saturation", 1.0),
                    gamma=params.get("gamma", 1.0),
                )
            elif op_type == OperationType.SET_CAPTION_STYLE:
                committed_op = engine.apply_caption_style(
                    style_params=params,
                    apply_to_existing=params.get("apply_to_existing", True),
                )
            elif op_type == OperationType.SET_CAPTION_MODE:
                committed_op = engine.apply_caption_mode(
                    mode=params.get("mode", "sentence"),
                )
            elif op_type == OperationType.ADD_TRANSITION:
                committed_op = engine.apply_transition(
                    transition_type=params.get("transition_type", "fade"),
                    duration=params.get("duration", 1.0),
                )
            elif op_type == OperationType.SET_ASPECT_RATIO:
                committed_op = engine.apply_aspect_ratio(
                    aspect_ratio=params.get("aspect_ratio", "original"),
                )
            elif op_type == OperationType.SPLIT_CLIP:
                committed_op = engine.apply_split_clip(
                    split_time=float(params.get("split_time", params.get("time", params.get("at", 0.0)))),
                    time_basis=params.get("time_basis", "current_timeline"),
                )
            elif op_type == OperationType.DUPLICATE_CLIP:
                committed_op = engine.apply_duplicate_clip(
                    segment_id=params.get("segment_id", params.get("clip_id")),
                    index=int(params["index"]) if "index" in params and params["index"] is not None else None,
                )
            elif op_type == OperationType.VIDEO_TRANSFORM:
                committed_op = engine.apply_video_transform(
                    rotation_degrees=params.get("rotation_degrees"),
                    horizontal_flip=params.get("horizontal_flip"),
                    vertical_flip=params.get("vertical_flip"),
                )
            elif op_type == OperationType.BLUR_REGION:
                committed_op = engine.apply_blur_region(
                    blur_radius=params.get("blur_radius", 10.0),
                )
            elif op_type == OperationType.APPLY_PRESET:
                if params.get("preset") == "vertical_reel":
                    committed_op = engine.apply_create_reel(
                        target_duration_s=params.get("target_duration_s", 30.0),
                    )
                else:
                    committed_op = engine.apply_preset(
                        preset_name=params.get("preset", "cinematic"),
                    )
            elif op_type == OperationType.CREATE_REEL:
                committed_op = engine.apply_create_reel(
                    target_duration_s=params.get(
                        "target_duration_s", params.get("target_duration", 30.0)
                    ),
                )
            elif op_type == OperationType.AUDIO_DUCKING:
                committed_op = engine.apply_audio_ducking(
                    enabled=params.get("enabled", True),
                    attenuation_db=params.get("attenuation_db", 12.0),
                )
            elif op_type == OperationType.AUDIO_NORMALIZE:
                committed_op = engine.apply_audio_normalize(
                    enabled=params.get("enabled", True),
                )
            elif op_type == OperationType.AUDIO_DENOISE:
                committed_op = engine.apply_audio_denoise(
                    enabled=params.get("enabled", True),
                    reduction_db=params.get("reduction_db", 12.0),
                )
            elif op_type == OperationType.UNDO:
                committed_op = engine.undo()
            elif op_type == OperationType.REDO:
                committed_op = engine.redo()
            elif op_type == OperationType.RESTORE_EDIT:
                committed_op = engine.restore_edit_or_revision(target_operation_id=params.get("target_operation_id"), target_revision=params.get("target_revision"))
            else:
                return InstructionResult(
                    request_id=req_id,
                    status=InstructionStatus.REJECTED,
                    error_code="UNSUPPORTED_OPERATION",
                    before_summary=before_summary,
                    message=f"Unsupported operation type: {op_type}" + (f" {time_policy}" if time_policy else ""),
                    time_policy=time_policy,
                )

            # Persist timeline changes
            tl_hash = timeline_service.save_timeline(engine.timeline)
            after_summary = engine.timeline.summary()

            return InstructionResult(
                request_id=req_id,
                status=InstructionStatus.APPLIED,
                message=f"Successfully applied {op_type.value}" + (f" {time_policy}" if time_policy else ""),
                operations=[committed_op],
                before_summary=before_summary,
                after_summary=after_summary,
                warnings=warnings,
                timeline_hash=tl_hash,
                timeline_revision=engine.timeline.revision,
                duration_s=engine.timeline.total_output_duration,
                operation_id=committed_op.operation_id,
                time_policy=time_policy,
            )

        except Exception as e:
            # Operation failed -> timeline state was not committed due to atomicity in engine
            return InstructionResult(
                request_id=req_id,
                status=InstructionStatus.REJECTED,
                message=str(e) + (f" {time_policy}" if time_policy else ""),
                error_code="OPERATION_FAILED",
                before_summary=before_summary,
                timeline_revision=engine.timeline.revision,
                duration_s=engine.timeline.total_output_duration,
                time_policy=time_policy,
            )


instruction_service = InstructionService()
