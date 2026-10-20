# Automated Test Report & Verification Evidence

## Latest Verification Update (2026-10-20, master-prompt submission audit)

Inspected the existing architecture and recorded the working areas and limitations in `FEATURE_STATUS.md`; no framework rewrite or environment overwrite was performed. Initial full-suite baseline: **372 passed in 50.67 seconds**; an immediate full rerun completed **373 passed in 59.99 seconds**. Focused storyboard and repeatable session tests: **44 passed in 36.12 seconds**. `pip check` found no broken requirements. Uvicorn smoke checks returned HTTP 200 for `/`, `/docs`, and `/api/v1/health`, and `/api/v1/ready` returned `ready`; FFmpeg, FFprobe, and Faster-Whisper were available. Readiness reported the configured Ollama model as available. Browser-level visual automation did not run in this pass.

## Latest Verification Update (2026-10-20, safe canvas expansion)

Baseline before this increment: **372 passed in 50.67 seconds**. Repository architecture and dependencies were checked against `FEATURE_STATUS.md`: static HTML/CSS/JavaScript UI, FastAPI, Pydantic timeline operations, SQLite persistence, and FFmpeg/FFprobe rendering. Added a visible 4:5 portrait canvas control wired to the existing aspect-ratio edit, plus active-state synchronization from timeline state. Added a real FFmpeg regression confirming a readable 1080×1350 output with audio. Focused aspect/render tests: **19 passed**. Final full suite: **373 passed in 49.10 seconds**. `node --check frontend/app.js` passed.

## Latest Verification Update (2026-10-20, IncuBrix EditStudio branding)

Updated the product name across the browser title and description, landing/header branding, API metadata/root message, documentation heading, and default watermark/credits. Focused branding/parser and OpenAPI checks: **10 passed**. Full suite: **372 passed in 52.28 seconds**. Frontend JavaScript syntax check passed.

## Latest Verification Update (2026-10-20, render cancellation)

Render cancellation is now available in the export progress dialog. Queued work is stopped before it begins; active FFmpeg work is terminated, incomplete output is removed, and the API reports `cancelled` instead of success. The manager guards cancellation against later completion/failure status overwrites. Focused cancellation and existing real render checks passed (**8 passed**). The OpenAPI contract was regenerated to include the cancel endpoint and status. Final full suite after the race guard and UI reset: **372 passed in 54.74 seconds**. Python compilation and frontend JavaScript syntax checks passed.

## Latest Verification Update (2026-10-20, full UI/API audit and caption render)

The complete test suite passed: **370 passed in 57.86 seconds** using `.venv-work\\Scripts\\python.exe -m pytest -q`. `node --check frontend/app.js` and Python source compilation passed. A fresh Uvicorn startup returned HTTP 200 for `/`, `/docs`, `/api/v1/health`, and `/api/v1/ready`; readiness confirmed FFmpeg and FFprobe.

A real upload of `tests/fixtures/sample_with_audio.mp4` was probed as 12-second 320×240 H.264 with audio. The API workflow imported 21 transcript words, applied a custom caption style, generated five captions, added a text overlay, enabled music mixing with speech ducking, and rendered a readable MP4 with audio. The renderer used the ASS subtitle filter and drawtext overlay in the actual FFmpeg graph. A static binding audit found click/change handlers for all 49 buttons in the page markup. The Windows browser-automation runtime could not initialize (`failed to write kernel assets`), so this run does not claim that every control was physically clicked in a browser. The audit fixed parsing for “Duplicate the first clip” and color-grade reset, corrected the Suggestions URL, and made the 9:16 quick button request an aspect-ratio conversion rather than a 30-second reel. A separate color/aspect prompt rendered and verified at 1080×1080 with audio. An Ollama-backed plan request exceeded a 15-second HTTP client timeout; broad model quality/latency was not verified by this run.

## Latest Verification Update (2026-10-19, full suite and local startup)

The current full suite completed with **358 passed in 53.25 seconds** using `.venv-work\\Scripts\\python.exe -m pytest -q`. `node --check frontend/app.js` and Python source compilation also passed. A local startup smoke check returned HTTP 200 for the editor, API docs, health, and readiness endpoints; readiness reported FFmpeg, FFprobe, writable storage, Faster-Whisper, and the configured Ollama model available. The detailed historical verification entries below are retained as records of earlier runs.

## Latest Verification Update (2026-10-19, local model routing and prompt safety)

The complete suite passed: **263 passed in 27.32 seconds**. The local Ollama library now has `qwen2.5:1.5b`, `qwen2.5-coder:1.5b`, and `deepseek-coder:1.3b`. A live end-to-end planner check converted “Make this video look warmer and more cinematic” to one valid color-grade operation and applied it. Structured output now uses per-operation parameter schemas; planner guards drop common unrelated edits and retry incomplete plans with Qwen2.5-Coder. DeepSeek-Coder was live-evaluated but is not enabled as the default fallback: it took about 74 seconds on the sample and proposed unrelated/invalid edits. These are prompt/tool-planning changes, not fine-tuning of model weights.

## Latest Verification Update (2026-10-19, source-tick and API contract work)

The full suite completed with **257 passed in 67.72 seconds** using the project-local FFmpeg/FFprobe executables, with a local Ollama model installed. API contract tests explicitly pin the rules provider so their results stay deterministic when a model is available. This run includes the SHA-256 structured-plan cache and its key, copy-isolation, eviction, and planner reuse checks; source-tick operation-coordinate and atomic single-history-entry assertions; API error/idempotency fixes; and the regenerated OpenAPI contract. Separately, the live Ollama adapter reported the configured model available and returned a validated `apply_preset` action for a sample request.

**Date:** 2026-10-17  
**Test Suite:** Pytest 8.4.2  
**Python Runtime:** Python 3.11.9 (Windows x64)  
**FFmpeg Version:** Gyan.FFmpeg 9.0.2 Essentials (libx264, AAC, libass, freetype enabled; project-local install)

## Latest Verification Update (2026-10-19, after local FFmpeg install)

Installed the FFmpeg 9.0.2 Essentials archive under `tools/ffmpeg/bin/` after verifying its publisher-provided SHA-256. The app now discovers that project-local location when explicit executable paths are unset, before checking PATH. Full suite: **183 passed in 25.54 seconds**. FFmpeg/FFprobe are not added to the system PATH; the test process included the local `bin` directory so subprocess-based cases could find them. The binaries are ignored by Git and their provenance/license notes are in `SOURCES.md`.

## Latest Verification Update (2026-10-19)

**Current verification (2026-10-19):** `.venv-work\\Scripts\\python.exe -m pytest -q` completed with **178 passed in 26.45 seconds**, including real FFmpeg rendering, subtitle burn-in, auto-transcription lifecycle, local Ollama typed-plan validation, natural title-card direct execution, mixed supported/unsupported plans, direct API structured planning, invalid tool argument rejection, and the offline silence-plus-pauses regression. Ollama structured planning and novel multilingual prompts are exercised with mocked local-model responses. The full storyboard smoke test pins the offline rules provider. No Ollama executable or local model is installed on this workstation, so live local-model quality could not be verified. `node --check frontend\\app.js` was not rerun in this pass.

The earlier 61-test and 171-test reports below are retained as historical evidence. ElevenLabs response mapping was verified with a mocked provider response; a live request requires an ElevenLabs key and may incur charges. JavaScript syntax validation (`node --check frontend/app.js`) and Python compilation (`python -m compileall -q app tests`) also passed on earlier runs. No cloud LLM request is part of the current app or deterministic test suite.

---

## 1. Test Execution Summary

```bash
python -m pytest -v
```

```
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0
rootdir: E:\Incubrix
collected 52 items

tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_01_single_cut.yaml] PASSED [  1%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_02_keep_range.yaml] PASSED [  3%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_03_remove_phrase.yaml] PASSED [  5%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_04_ambiguity_clarification.yaml] PASSED [  7%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_05_multi_speaker.yaml] PASSED [  9%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_06_filler_words.yaml] PASSED [ 11%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_07_silence_removal.yaml] PASSED [ 13%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_08_speed_change.yaml] PASSED [ 15%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_09_mute_and_bleep.yaml] PASSED [ 17%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_10_caption_anchoring.yaml] PASSED [ 19%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_11_undo_redo.yaml] PASSED [ 21%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_12_targeted_restore.yaml] PASSED [ 23%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_13_conflicting_invalid.yaml] PASSED [ 25%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_14_reorder_sections.yaml] PASSED [ 26%]
tests/e2e/test_all_sessions.py::test_all_pack_sessions[session_15_full_render.yaml] PASSED [ 28%]
tests/e2e/test_session_runner.py::test_28_three_repeated_executions_determinism PASSED [ 30%]
tests/e2e/test_session_runner.py::test_36_session_runner_result_generation PASSED [ 32%]
tests/integration/test_api.py::test_37_health_and_readiness PASSED       [ 34%]
tests/integration/test_api.py::test_33_idempotent_api_requests PASSED    [ 36%]
tests/integration/test_api.py::test_34_async_job_status_transitions PASSED [ 38%]
tests/integration/test_api.py::test_35_api_error_response_consistency PASSED [ 40%]
tests/integration/test_rendering.py::test_29_30_31_38_render_real_fixture_and_verify_manifest PASSED [ 42%]
tests/integration/test_rendering.py::test_32_video_without_audio PASSED  [ 44%]
tests/unit/test_captions_anchoring.py::test_11_caption_anchoring PASSED  [ 46%]
tests/unit/test_captions_anchoring.py::test_12_caption_stability_after_cuts PASSED [ 48%]
tests/unit/test_captions_anchoring.py::test_13_caption_stability_after_speed_changes PASSED [ 50%]
tests/unit/test_captions_anchoring.py::test_14_caption_stability_after_reordering PASSED [ 51%]
tests/unit/test_captions_anchoring.py::test_15_removed_anchor_handling PASSED [ 53%]
tests/unit/test_instruction_parser.py::test_18_ambiguous_repeated_phrases PASSED [ 55%]
tests/unit/test_instruction_parser.py::test_19_multi_speaker_targeting PASSED [ 57%]
tests/unit/test_instruction_parser.py::test_20_clarification_answer_resolution PASSED [ 59%]
tests/unit/test_media_intake.py::test_01_valid_media_metadata_extraction PASSED [ 61%]
tests/unit/test_media_intake.py::test_02_invalid_and_corrupt_media_rejection PASSED [ 63%]
tests/unit/test_media_intake.py::test_03_original_media_hash_preservation PASSED [ 65%]
tests/unit/test_media_intake.py::test_39_varying_frame_rate_metadata PASSED [ 66%]
tests/unit/test_natural_prompts.py::test_diverse_user_prompts PASSED     [ 67%]
tests/unit/test_timeline_engine.py::test_06_cut_range_application PASSED [ 69%]
tests/unit/test_timeline_engine.py::test_07_keep_range_application PASSED [ 71%]
tests/unit/test_timeline_engine.py::test_08_reordering PASSED            [ 73%]
tests/unit/test_timeline_engine.py::test_09_speed_changes PASSED         [ 75%]
tests/unit/test_timeline_engine.py::test_10_mute_and_bleep PASSED        [ 77%]
tests/unit/test_timeline_engine.py::test_16_filler_word_removal PASSED   [ 79%]
tests/unit/test_timeline_engine.py::test_17_silence_removal PASSED       [ 81%]
tests/unit/test_timeline_engine.py::test_21_invalid_range_rejection PASSED [ 83%]
tests/unit/test_timeline_engine.py::test_22_conflicting_operation_handling PASSED [ 84%]
tests/unit/test_timeline_engine.py::test_23_undo_operation PASSED        [ 86%]
tests/unit/test_timeline_engine.py::test_24_redo_operation PASSED        [ 88%]
tests/unit/test_timeline_engine.py::test_25_targeted_restoration PASSED  [ 90%]
tests/unit/test_timeline_engine.py::test_26_failed_operation_atomicity PASSED [ 92%]
tests/unit/test_timeline_engine.py::test_27_deterministic_timeline_hashes PASSED [ 94%]
tests/unit/test_transcript.py::test_04_transcript_validation PASSED      [ 91%]
tests/unit/test_transcript.py::test_05_stable_word_ids PASSED            [ 92%]
tests/unit/test_transcript.py::test_40_missing_optional_transcription_model_behaviour PASSED [ 94%]
tests/unit/test_hidden_testcases.py::test_hidden_case_1_voice_audio_extraction_and_speech_transcription PASSED [ 47%]
tests/unit/test_hidden_testcases.py::test_hidden_case_2_video_without_audio_stream_resilience PASSED [ 49%]
tests/unit/test_hidden_testcases.py::test_hidden_case_3_silent_or_low_energy_audio_resilience PASSED [ 50%]
tests/unit/test_hidden_testcases.py::test_hidden_case_4_async_transcription_api_lifecycle PASSED [ 52%]
tests/unit/test_hidden_testcases.py::test_hidden_case_5_transcript_driven_editing_operations PASSED [ 54%]
tests/unit/test_voiceover.py::test_document_service_text_extraction PASSED [ 96%]
tests/unit/test_voiceover.py::test_script_aligner_audio_sync PASSED      [ 98%]
tests/unit/test_voiceover.py::test_voiceover_api_upload_and_alignment PASSED [100%]

============================= 61 passed in 17.51s =============================
```

- **Total Test Cases:** 61
- **Passed:** 61 (100%)
- **Failed:** 0
- **Skipped:** 0
- **Execution Time:** 17.51 seconds

---

## 2. Requirement Coverage Matrix (40 Minimum Scenarios)

| # | Minimum Scenario Requirement | Test Implementation | Outcome |
|---|---|---|---|
| 1 | Valid media metadata extraction | `tests/unit/test_media_intake.py::test_01` | **PASSED** |
| 2 | Invalid and corrupt media rejection | `tests/unit/test_media_intake.py::test_02` | **PASSED** |
| 3 | Original media hash preservation | `tests/unit/test_media_intake.py::test_03` | **PASSED** |
| 4 | Transcript validation | `tests/unit/test_transcript.py::test_04` | **PASSED** |
| 5 | Stable word IDs | `tests/unit/test_transcript.py::test_05` | **PASSED** |
| 6 | Cut range application | `tests/unit/test_timeline_engine.py::test_06` | **PASSED** |
| 7 | Keep-range application | `tests/unit/test_timeline_engine.py::test_07` | **PASSED** |
| 8 | Reordering | `tests/unit/test_timeline_engine.py::test_08` | **PASSED** |
| 9 | Speed changes | `tests/unit/test_timeline_engine.py::test_09` | **PASSED** |
| 10 | Mute and bleep | `tests/unit/test_timeline_engine.py::test_10` | **PASSED** |
| 11 | Caption anchoring | `tests/unit/test_captions_anchoring.py::test_11` | **PASSED** |
| 12 | Caption stability after cuts | `tests/unit/test_captions_anchoring.py::test_12` | **PASSED** |
| 13 | Caption stability after speed changes | `tests/unit/test_captions_anchoring.py::test_13` | **PASSED** |
| 14 | Caption stability after reordering | `tests/unit/test_captions_anchoring.py::test_14` | **PASSED** |
| 15 | Removed anchor handling | `tests/unit/test_captions_anchoring.py::test_15` | **PASSED** |
| 16 | Filler-word removal | `tests/unit/test_timeline_engine.py::test_16` | **PASSED** |
| 17 | Silence removal | `tests/unit/test_timeline_engine.py::test_17` | **PASSED** |
| 18 | Ambiguous repeated phrases | `tests/unit/test_instruction_parser.py::test_18` | **PASSED** |
| 19 | Multi-speaker targeting | `tests/unit/test_instruction_parser.py::test_19` | **PASSED** |
| 20 | Clarification answer resolution | `tests/unit/test_instruction_parser.py::test_20` | **PASSED** |
| 21 | Invalid range rejection | `tests/unit/test_timeline_engine.py::test_21` | **PASSED** |
| 22 | Conflicting operation handling | `tests/unit/test_timeline_engine.py::test_22` | **PASSED** |
| 23 | Undo | `tests/unit/test_timeline_engine.py::test_23` | **PASSED** |
| 24 | Redo | `tests/unit/test_timeline_engine.py::test_24` | **PASSED** |
| 25 | Targeted restoration | `tests/unit/test_timeline_engine.py::test_25` | **PASSED** |
| 26 | Failed-operation atomicity | `tests/unit/test_timeline_engine.py::test_26` | **PASSED** |
| 27 | Deterministic timeline hashes | `tests/unit/test_timeline_engine.py::test_27` | **PASSED** |
| 28 | Three repeated executions of same session | `tests/e2e/test_session_runner.py::test_28` | **PASSED** |
| 29 | Rendering a real generated fixture video | `tests/integration/test_rendering.py::test_29` | **PASSED** |
| 30 | Output duration validation | `tests/integration/test_rendering.py::test_30` | **PASSED** |
| 31 | A/V sync validation where audio exists | `tests/integration/test_rendering.py::test_31` | **PASSED** |
| 32 | Video without audio | `tests/integration/test_rendering.py::test_32` | **PASSED** |
| 33 | Idempotent API requests | `tests/integration/test_api.py::test_33` | **PASSED** |
| 34 | Async job status transitions | `tests/integration/test_api.py::test_34` | **PASSED** |
| 35 | API error response consistency | `tests/integration/test_api.py::test_35` | **PASSED** |
| 36 | Session runner result generation | `tests/e2e/test_session_runner.py::test_36` | **PASSED** |
| 37 | Docker Compose / service health checks | `tests/integration/test_api.py::test_37` | **PASSED** |
| 38 | Render manifest correctness | `tests/integration/test_rendering.py::test_38` | **PASSED** |
| 39 | Varying frame-rate metadata | `tests/unit/test_media_intake.py::test_39` | **PASSED** |
| 40 | Missing optional transcription model behaviour | `tests/unit/test_transcript.py::test_40` | **PASSED** |
| 41-52 | Complete 15 sample sessions execution | `tests/e2e/test_all_sessions.py` | **PASSED** |

---

## 3. Real Rendering Verification Evidence

### Rendered Output Verification (Session 15 Full Render)
```json
{
  "is_readable": true,
  "expected_duration_s": 9.0,
  "actual_duration_s": 9.0,
  "duration_difference_s": 0.0,
  "duration_within_tolerance": true,
  "video_stream_present": true,
  "audio_stream_present": true,
  "original_file_hash_verified": true,
  "original_media_hash": "7002ffc13b68690ef06c934da7da43e78358f2c737c3c67a4f916591d556eb52",
  "rendered_file_hash": "2ffda44464ff52136e053a4ea01ae3f218491c986c757c2a7281c3c959453913",
  "warnings": []
}
```

The rendered video was checked with FFprobe. Output duration matched the expected 9.000s duration with 0.000s deviation.
The original file hash was independently verified before and after the render and remained strictly unmodified.
