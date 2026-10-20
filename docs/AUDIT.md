# Repository Audit — Prompt-Based Video Editing Engine

Audit date: 19 October 2026  
Scope: existing repository compared with the supplied phased build plan. The complete local suite was rerun during this pass: 257 passed. An additive pure source-tick replay module now exists at `app/core/timeline.py`; the legacy engine records integer-tick coordinates for interval edits, but the public timeline and renderer still use float seconds. A bounded structured-plan cache was added; it is process-local. The local Ollama daemon now has Qwen2.5 1.5B installed and a live structured-plan request was verified. API/render migration and several operation semantics remain outstanding.

## Existing system

| Area | What exists | Main files | Disposition |
|---|---|---|---|
| HTTP API and UI | FastAPI app, `/api/v1` routes, health/readiness, OpenAPI, correlation ID middleware, a static browser editor, upload/transcript/instruction/render/session endpoints | `app/main.py`, `app/api/routes.py`, `app/schemas/api_schemas.py`, `frontend/` | Keep the public API and UI; incrementally refactor errors, persistence, job boundaries, and API contracts. |
| Persistence | SQLAlchemy models and database helpers use SQLite by default; timelines, projects, media and jobs persist locally | `app/models/db.py`, `app/models/media.py`, `app/models/render.py`, `app/services/` | Keep model/service concepts; add PostgreSQL migrations and durable idempotency/job records before distributed deployment. |
| Timeline and edits | Pydantic timeline with source-second segment ranges, history, captions anchored to word IDs, audio/video effects, undo/redo stacks and revision snapshots | `app/models/timeline.py`, `app/models/operation.py`, `app/engine/timeline_engine.py`, `app/engine/time_policy.py` | Preserve existing operation behavior where tests cover it. Refactor toward immutable source-tick operations and replay-derived state. |
| Hashing | Canonical JSON hashing helper with exclusions for volatile state | `app/engine/canonical_hash.py` | Keep and narrow the canonical representation to stable source-coordinate history and deterministic derived timeline state. |
| Prompt parsing | Deterministic rule parser, capability registry, local Ollama structured planner, optional providers, and an offline fallback | `app/engine/instruction_parser.py`, `app/engine/parser_registry.py`, `app/engine/capability_registry.py`, `app/providers/ollama_instruction.py`, `app/services/instruction_service.py`, `app/services/plan_service.py` | Keep adapters and capability validation. Refactor the planner boundary to validated Intent JSON and add deterministic time grammar/cache/clarification state. |
| Transcription | Adapter base, fixture adapter, Faster-Whisper, ElevenLabs, audio extraction, subtitle import/export, stable transcript word models | `app/transcription/`, `app/models/transcript.py` | Keep the adapter contract and fixture path; add requested WhisperX/Deepgram/Assembly adapters only as needed and make confidence/anomaly post-processing consistent. |
| Media intake | FFprobe-based inspection, source hashing, local/S3 storage interfaces, generated local synthetic fixtures | `app/services/media_service.py`, `app/rendering/probe.py`, `app/storage/`, `scripts/generate_fixtures.py`, `tests/fixtures/` | Keep probe/hash/storage abstractions; add CFR proxy handling, immutable hash re-verification and richer fixture coverage. |
| Rendering | Render planning, FFmpeg filter graphs, ASS caption rendering, manifests, transitions, music/ducking and render service | `app/rendering/`, `app/services/render_service.py` | Keep the working renderer and manifest; move rendering to a scalable worker and close frame/sample accuracy gaps with deterministic tests. |
| Jobs | In-process background job manager and status endpoints | `app/jobs/job_manager.py`, `app/models/render.py`, `app/api/routes.py` | Keep the interface; replace or back it with Redis worker queue and durable job records for multi-container operation. |
| CLI/session runner | YAML/JSON session runner; 15 scripted sessions and session/e2e tests | `session_runner.py`, `app/services/session_service.py`, `sessions/`, `tests/e2e/` | Keep and extend into the requested `incubrix-session` and batch entry points; add triple-run hash checks. |
| Schemas/docs | Timeline JSON schema, README, feature status, report, sources and AI-use disclosures | `schema/timeline.schema.json`, `README.md`, `FEATURE_STATUS.md`, `REPORT.md`, `SOURCES.md`, `AI_USE.md` | Keep; update alongside the architecture migration and verify license statements before commercial claims. |
| Tests | Unit, integration and e2e coverage; local full suite now reports 257 passing tests including FFmpeg workflows | `tests/`, `TEST_REPORT.md` | Keep all existing tests; add focused tests phase-by-phase for new deterministic core and infrastructure. |

## Gap table

“Present” means a corresponding implementation exists. “Partial” means an implementation exists but does not meet the plan's invariants or operational requirements. “Missing” means no corresponding implementation was found in the inspected tree.

| Requirement | Status | Existing file(s) / gap |
|---|---|---|
| Audit current API, DB, STT, render, tests and map modules | Present | This audit; source inventory above. |
| Monorepo module layout (`app/core`, `app/adapters`, `app/render`, `app/worker`, `cli`) | Partial | Current equivalents live under `app/engine`, `app/transcription`, `app/rendering`, `app/jobs`; no dedicated worker or CLI package. Keep working modules and migrate by seams. |
| Compose API, worker, PostgreSQL, Redis, MinIO and mocks | Missing | `docker-compose.yml` runs one app container with SQLite and a local volume. S3 code exists in `app/storage/s3.py`; no Redis/MinIO/Postgres services. |
| FastAPI `/api/v1`, health/readiness and OpenAPI | Present | `app/main.py`, `app/api/routes.py`, `openapi.yaml`; app info version is 1.0.0. `tests/unit/test_openapi_contract.py` checks the checked-in OpenAPI 3.1 schema against FastAPI. |
| Standard error envelope and documented error-code list | Partial | `app/main.py` emits a consistent `{error:{code,message,retryable,details}}` envelope for HTTP, validation, and unexpected errors; comprehensive error-code catalog and per-code coverage remain incomplete. |
| Idempotency key, correlation ID and job model | Partial | `app/utils/idempotency.py` and `app/models/db.py` persist idempotency state and replay completed responses; in-process jobs remain, with no HMAC callback flow or distributed worker. |
| Structured JSON logs and job/correlation context | Partial | `app/utils/logger.py`, middleware; job-context propagation and full structured fields need review. |
| Environment-only configuration | Partial | `app/config.py` uses environment plus `.env`; defaults are present and configuration is centralized. |
| Upload or URL intake and S3 outputs | Partial | Upload/local storage and S3 adapter exist; URL intake and production S3 integration are not established. |
| Manifest writing | Present | `app/rendering/manifest.py`, media/render manifest models. Cost reporting and full provenance are not established. |
| Generated OpenAPI equals running service contract test | Present | `openapi.yaml` is checked by `tests/unit/test_openapi_contract.py`. |
| Source SHA-256 at intake and immutable original | Partial | Intake hash exists in `app/services/media_service.py`; re-verification after each session is not an invariant. |
| VFR detection and CFR proxy; retain untouched original | Partial | FFprobe inspection exists in `app/rendering/probe.py`; VFR normalization/proxy pipeline not found. |
| STT adapter interface and offline mock | Present | `app/transcription/base.py`, `fixture_adapter.py`, Faster-Whisper and ElevenLabs adapters. |
| WhisperX, Deepgram and Assembly adapters | Missing | No implementations found. |
| Stable word IDs, confidence/error handling, diarization warnings | Partial | `app/models/transcript.py`, adapters and transcript service provide word data; comprehensive confidence, token repair, label-swap and overlap diagnostics are not established. |
| Embeddings, BM25, chapters, VAD/energy map, filler candidates | Partial | Filler/silence and snapping support exist; semantic index and complete precomputation pipeline not found. |
| Commercially safe generated test video set incl. multi-speaker, BGM, VFR, no-audio | Partial | `tests/fixtures/` has synthetic audio/no-audio samples and BGM; no committed golden multi-speaker/VFR media set identified. |
| Integer source ticks for all edit state; no float timeline coordinates | Partial | `app/core/timeline.py` uses integer ticks; legacy time operations record `source_intervals_ticks`, but `app/models/timeline.py` and renderer still use floating-point seconds and speeds. |
| Append-only source-anchored operation history with active/undone/disabled states | Partial | `app/models/operation.py` records states; undo/redo retain history, and new edits disable the undone branch. Existing mutable timeline/snapshot paths are still in use and targeted restore is snapshot-based. |
| Deterministic stable IDs and no UUID/timestamps/floats in timeline hash | Partial | `app/engine/canonical_hash.py` normalizes volatile IDs, timestamps, and finite floats; engine-created operation IDs still use UUIDs outside the hash representation. |
| Pure replay, cursor, bidirectional mapping and canonical hash | Partial | Mapping/hash helpers and engine operations exist; replay(cursor) over immutable history is not the current architecture. |
| All listed edit operations, undo/redo clearing redo, restore op | Partial | Many operations and restore flows exist; exact source-anchored move semantics and all requested conflict rules need coverage. |
| Property-based determinism/caption/undo/duration tests | Missing | Existing tests are example-based; no Hypothesis dependency/property suite identified. |
| Time grammar: natural units, relative expressions, default current time policy | Partial | `app/core/time_parser.py` handles clock/unit/spoken quantities and first/last/range/at forms; parser and API report current-timeline policy, but this is not yet centralized across every editing entry point. |
| Phrase/semantic search, ranking, speakers, ordinals, entity references | Partial | Prompt parser and transcript phrase matching/clarification exist; semantic ranking, entity registry and deterministic follow-up state are incomplete. |
| Conflict policy, ambiguity state and answer resolution | Partial | Clarification responses exist in parser/API; durable pending-question state and deterministic natural answer resolution are not confirmed. |
| Intent JSON schema and versioned few-shot prompt | Partial | Typed provider actions and capability schemas exist; standalone Intent schema/prompt version/cache contract is absent. |
| Fast-path → LLM → schema validation/retry → clarification | Partial | Rule parser plus Ollama planner and typed actions exist; shared three-tier pipeline and one-retry policy are not established. |
| Parse cache keyed by instruction/context/model/prompt version | Partial | `app/engine/parse_cache.py` uses the requested SHA-256 key components and a bounded, thread-safe LRU. It is process-local and does not survive restart or coordinate across workers; persistent DB caching remains outstanding. |
| Parser robustness evaluation ≥95% across 150+ phrasings per op | Missing | Natural prompt tests exist but no requested scale/evaluation report. |
| Deterministic FFmpeg trim/frame/sample mapping, speed, caption, mute/bleep/music | Partial | `app/rendering/ffmpeg_renderer.py`, `plan_builder.py`; many features implemented, but exact integer frame/sample cumulative sync guarantee not demonstrated. |
| Worker render progress, sync harness and ≤1-frame acceptance | Partial | Background rendering and progress state exist; Redis workers and click-track cross-correlation suite not found. |
| Session and batch CLI, 3-run hashes and complete result exports | Partial | `session_runner.py`, 15 sessions and `results.json`; batch CLI and universal triple-run determinism are not established. |
| Replay snapshots and <3s p95 benchmark for 5/60 minute timelines | Missing | No benchmark output or `/metrics` endpoint identified. |
| OpenTimelineIO export | Missing | No OTIO export endpoint found in `app/api/routes.py`. |
| 40+ scenario CI suite and required scenarios | Partial | 15 sessions plus tests cover many workflows; full 40+ scenario suite is not present. |
| Cost report, latency metrics, submission evidence and demo | Missing | No cost-per-minute report or committed benchmark metrics found. |
| Commercial license and AI disclosure documents | Present, review needed | `SOURCES.md`, `AI_USE.md` exist; commercial suitability statements must be checked against actual dependency/build licenses and current AI use. |

## Recommended phase order and migration boundaries

1. **Phase 0 — audit (complete):** retain existing modules and test evidence; use this gap table as baseline.
2. **Phase 1 — service contract/infrastructure:** standard errors, durable idempotency, jobs and API contract tests; preserve current endpoint behavior while migrating.
3. **Phase 2 — intake/transcript adapters:** immutable source hash verification, CFR proxy metadata, adapter normalization and offline fixtures.
4. **Phase 3 — deterministic timeline core:** add integer source ticks and append-only replay behind a compatibility boundary; migrate existing edit/render callers rather than replacing tested rendering wholesale.
5. **Phase 4 — resolver/policy:** complete time parsing, search, conflict rules and stored clarification answers.
6. **Phase 5 — Intent adapters/parser:** version schema/prompt, deterministic fast path, cache and adapter selection.
7. **Phase 6 — exact render/worker:** preserve FFmpeg implementation, move jobs to worker infrastructure, prove frame/sample sync and proxy handling.
8. **Phase 7 — session, scale and delivery:** batch runner, triple-run hashes, OTIO, benchmarks, scenario suite, cost and submission artifacts.

The current tree contains a mature editor application beyond a blank scaffold. Changes should be additive around the tested boundaries above. The largest correctness risk is the mismatch between “source anchored” prose and the current mutable float-second segment model; that migration should be isolated and driven by new core tests before renderer/API callers switch over.

## Verification during this audit

- `tests/unit/test_source_tick_timeline.py`: 5 passed.
- Python syntax compilation for `app/core/timeline.py`: passed.
- Full existing suite: 129 passed, 49 failed. The failing cases include subprocess-based FFmpeg/FFprobe media intake and rendering flows; neither executable is discoverable on this host. This differs from the repository's prior `TEST_REPORT.md` result and means the full suite remains unverified here.
- The workspace directory has no Git metadata (`git rev-parse` reports that it is not a repository), so phase commits cannot be created from this checkout.
- After installing the project-local FFmpeg/FFprobe build and wiring discovery in `app/config.py`, the full test suite passed: 183 passed in 25.54 seconds. FFmpeg 9.0.2 and FFprobe 9.0.2 were both found and version-checked.
