import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from app.config import settings
from app.engine.canonical_hash import compute_timeline_hash
from app.models.operation import InstructionResult, InstructionStatus
from app.models.transcript import Transcript
from app.rendering.ffmpeg_renderer import render_timeline
from app.services.instruction_service import instruction_service
from app.services.media_service import media_service
from app.services.timeline_service import timeline_service
from app.transcription.fixture_adapter import FixtureTranscriptionAdapter


class SessionExecutionError(Exception):
    pass


def load_session_file(session_path: str | Path) -> Dict[str, Any]:
    p = Path(session_path)
    if not p.is_file():
        raise FileNotFoundError(f"Session file not found: {session_path}")

    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    if not isinstance(data, dict):
        raise ValueError("Session file must be a top-level dictionary or YAML mapping")
    return data


def execute_session(session_data: Dict[str, Any], output_results_path: Optional[str] = "results.json") -> Dict[str, Any]:
    """
    Execute complete end-to-end editing session using the real timeline engine.
    Never hard-codes output.
    """
    video_path = session_data.get("video_path")
    if not video_path:
        raise SessionExecutionError("Session file missing required 'video_path'")

    v_path = Path(video_path)
    if not v_path.is_file():
        raise SessionExecutionError(f"Video file does not exist: {video_path}")

    # 1. Intake media
    with open(v_path, "rb") as vf:
        manifest = media_service.intake_uploaded_file(vf, v_path.name)

    # 2. Intake transcript
    transcript = None
    transcript_path = session_data.get("transcript_path")
    transcript_inline = session_data.get("transcript")
    if transcript_path:
        tp = Path(transcript_path)
        if tp.is_file():
            adapter = FixtureTranscriptionAdapter(tp)
            transcript = adapter.transcribe(str(manifest.storage_path))
    elif transcript_inline:
        adapter = FixtureTranscriptionAdapter(transcript_inline)
        transcript = adapter.transcribe(str(manifest.storage_path))

    # 3. Initialize timeline
    timeline = timeline_service.initialize_timeline(manifest, transcript)
    media_id = manifest.media_id

    # 4. Process instructions sequentially
    instructions = session_data.get("instructions", [])
    clarification_answers = session_data.get("clarification_answers", {})
    # clarification_answers can be a dict mapping instruction index string (e.g. "0") or question substring to choice

    instruction_results: List[Dict[str, Any]] = []
    initial_hash = compute_timeline_hash(timeline.model_dump())

    for idx, instr in enumerate(instructions):
        instr_text = instr if isinstance(instr, str) else instr.get("text", "")
        res = instruction_service.process_instruction(media_id, instr_text)

        # Handle pending clarification if clarification answers provided
        if res.status == InstructionStatus.NEEDS_CLARIFICATION:
            ans = clarification_answers.get(str(idx)) or clarification_answers.get(instr_text)
            if not ans and isinstance(clarification_answers, list) and idx < len(clarification_answers):
                ans = clarification_answers[idx]

            if ans and res.operation_id:
                # Resolve clarification
                resolved_res = instruction_service.resolve_clarification(res.operation_id, str(ans))
                instruction_results.append({
                    "instruction_index": idx,
                    "instruction": instr_text,
                    "clarification_question": res.clarification_question,
                    "clarification_options": [opt.model_dump() for opt in res.options],
                    "clarification_answer": ans,
                    "result": resolved_res.model_dump(),
                })
                res = resolved_res
            else:
                instruction_results.append({
                    "instruction_index": idx,
                    "instruction": instr_text,
                    "result": res.model_dump(),
                })
        else:
            instruction_results.append({
                "instruction_index": idx,
                "instruction": instr_text,
                "result": res.model_dump(),
            })

    # Retrieve final timeline
    final_timeline = timeline_service.get_timeline(media_id)
    final_hash = compute_timeline_hash(final_timeline.model_dump())

    # 5. Optional render
    render_result = None
    if session_data.get("render", False):
        manifest_res = render_timeline(
            timeline=final_timeline,
            media_source_path=manifest.storage_path,
            output_dir=settings.RENDER_OUTPUT_DIR,
        )
        render_result = manifest_res.model_dump()

    # 6. Check assertions if present
    assertions = session_data.get("assertions", {})
    expected_status = assertions.get("expected_last_status")
    if expected_status and instruction_results:
        last_res = instruction_results[-1]["result"]
        actual_status = last_res["status"].value if hasattr(last_res["status"], "value") else str(last_res["status"])
        if actual_status != expected_status:
            raise SessionExecutionError(f"Assertion failed: expected status '{expected_status}', got '{actual_status}'")

    expected_duration = assertions.get("expected_duration")
    if expected_duration is not None:
        actual_dur = final_timeline.total_output_duration
        if abs(actual_dur - float(expected_duration)) > 0.2:
            raise SessionExecutionError(f"Assertion failed: expected duration {expected_duration}s, got {actual_dur:.3f}s")

    expected_hash = assertions.get("expected_timeline_hash")
    if expected_hash and final_hash != expected_hash:
        raise SessionExecutionError(f"Assertion failed: expected hash {expected_hash}, got {final_hash}")

    output_summary = {
        "media_id": media_id,
        "original_media_hash": manifest.sha256_hash,
        "initial_timeline_hash": initial_hash,
        "final_timeline_hash": final_hash,
        "final_revision": final_timeline.revision,
        "final_duration_s": final_timeline.total_output_duration,
        "instruction_count": len(instructions),
        "results": instruction_results,
        "render_manifest": render_result,
        "history_count": len(final_timeline.history),
    }

    if output_results_path:
        with open(output_results_path, "w", encoding="utf-8") as f:
            json.dump(output_summary, f, indent=2)

    return output_summary
