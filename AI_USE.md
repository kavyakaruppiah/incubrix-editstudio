# AI Tools and Assistance Disclosure

This document honestly discloses the use of AI tools during the engineering and development of this repository.

---

## 1. AI Tooling Used

- **Primary Assistant:** Antigravity AI Coding Assistant (powered by Google DeepMind's Gemini model).
- **Environment:** Antigravity IDE on Windows x64.
- **Workflow:** Pair-programming and autonomous agentic workflow driven by natural-language requirements and continuous automated test verification loops.

---

## 2. Scope of AI Assistance

AI assistance was utilized across the following phases:

1. **Architecture & Schema Design:**
   - Drafting JSON Schema Draft 2020-12 for the deterministic video timeline.
   - Designing mathematical time policy models (source time vs. output timeline time).
2. **Deterministic Code Implementation:**
   - Authoring the core Python 3.11 modules:
     - `app/engine/timeline_engine.py` (atomic edits, reordering, speed scaling, undo/redo).
     - `app/engine/canonical_hash.py` (canonical serialisation excluding volatile fields).
     - `app/engine/instruction_parser.py` (deterministic regex rule matching and ambiguity resolution).
     - `app/rendering/plan_builder.py` and `ffmpeg_renderer.py` (FFmpeg subprocess filter compilation and ASS caption generation).
     - `app/api/routes.py` (FastAPI REST endpoints with idempotency and correlation IDs).
3. **Frontend UI Implementation:**
   - Authoring `frontend/index.html`, `frontend/app.css` (custom dark glassmorphism design system), and `frontend/app.js` (vanilla JS client logic without bulky frameworks).
4. **Test Suite Authoring & Debugging:**
   - Generating 52 automated test cases covering unit, integration, and end-to-end scenarios.
   - Inspecting failure logs, identifying root causes (e.g. walrus operator syntax, speaker regex boundaries, database deduplication, hash exclusions), and implementing verified fixes.

---

## 3. Human & Engineering Oversight

- All FFmpeg commands, filter graphs, and database schemas were validated through real execution and probe verification.
- No mocked renders, fabricated test outputs, or hard-coded results were accepted.
- Automated tests were run locally via `pytest` to guarantee 100% real passing execution.
