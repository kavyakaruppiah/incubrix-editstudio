# IncuBrix EditStudio

A professional, locally runnable AI-assisted video editing studio. IncuBrix EditStudio accepts video assets, maintains a reversible timeline, interprets natural-language editing instructions with persistent transcript anchoring, renders verified output through FFmpeg, and provides structured results for every instruction.

See [FEATURE_STATUS.md](FEATURE_STATUS.md) for the implementation audit, verified areas, and known gaps.

For deployment on Render, see [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md). The Docker image uses Render's runtime `PORT` automatically and stores persistent application data under `/app/data` when you attach a disk there.

---

## Prerequisites

- **Python 3.11+**
- **FFmpeg & FFprobe 6.0+** (with `libx264`, `aac`, and `libass` enabled)
- **Git** (optional)
- **Docker & Docker Compose** (optional, for containerized run)

FFmpeg and FFprobe can be supplied through `FFMPEG_BINARY` and `FFPROBE_BINARY`. If unset, the app checks `tools/ffmpeg/bin/` in this repository, then the system PATH. The project-local binaries are ignored by Git; see [SOURCES.md](SOURCES.md) for their version and license provenance.

---

## Installation & Setup

### 1. Clone & Set Up Virtual Environment

```bash
# Clone the repository
git clone <repo-url>
cd <repo-dir>

# Create and activate virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Generate Test Media Fixtures (Offline & Self-Contained)

```bash
python scripts/generate_fixtures.py
```
This generates `sample_with_audio.mp4`, `sample_no_audio.mp4`, and `sample_transcript.json` using local FFmpeg filters. No external media downloads are required.

### 4. Environment Configuration

Copy the example environment file:
```bash
cp .env.example .env
```
Key configuration options in `.env`:
- `APP_PORT=8000`: Local API and UI port.
- `STORAGE_BACKEND=local`: Media storage adapter (`local` or `s3`).
- `AUDIO_SNAPPING_ENABLED=true`: Low-energy audio boundary cut snapping.
- `GOOGLE_SPEECH_FALLBACK_ENABLED=false`: Keep transcription local by default. Enable only if you explicitly accept sending audio to Google's recognition service as a fallback.
- `FFMPEG_BINARY`: Optional custom path to FFmpeg binary (automatically discovered if omitted).
- `FFPROBE_BINARY`: Optional custom path to FFprobe binary.

### AI Prompt Planning

Prompt planning defaults to `INSTRUCTION_PROVIDER=auto`: it uses the configured Ollama model and retries incomplete/invalid plans with models listed in `OLLAMA_FALLBACK_MODELS`. For local development, configure a locally installed model and Ollama URL. For Render or another hosted deployment, this adapter also supports Ollama Cloud with `OLLAMA_BASE_URL=https://ollama.com`, `OLLAMA_MODEL` set to a cloud model, and `OLLAMA_API_KEY` set as a secret; it sends authenticated requests to Ollama Cloud's chat API. If Ollama is unavailable, `auto` uses Gemini only when `GEMINI_API_KEY` is configured; otherwise it visibly falls back to deterministic rules. Gemini is optional and may incur provider charges; requests sent to it leave the local machine. Use `INSTRUCTION_PROVIDER=rules` for offline deterministic behavior or `INSTRUCTION_PROVIDER=ollama` to require the configured Ollama provider without fallback.

Model weights are not fine-tuned by this setup: it specializes planning through the editor's registered tools, constrained per-tool JSON output, prompt safeguards, and regression tests. Qwen2.5-Coder is Apache-2.0; DeepSeek-Coder has additional use-based license restrictions.

The configured planner receives the complete request, registered editor tools, media metadata, and relevant transcript context. It returns typed JSON actions which are validated and executed by the deterministic timeline/FFmpeg engine. Models do not generate executable code or FFmpeg commands. Unsupported edits remain explicitly reported. Without an available AI provider, the offline rules parser recognizes only its supported deterministic wording; no provider can perform effects that the renderer does not implement.

### Optional ElevenLabs transcription

For word-timestamped cloud transcription, set `TRANSCRIPTION_BACKEND=elevenlabs` and `ELEVENLABS_API_KEY` in `.env`. The default `auto` backend also selects ElevenLabs when that key is configured; without the key it uses local Faster-Whisper. When enabled, the original uploaded media is sent to ElevenLabs for transcription and usage may incur charges. ElevenLabs Scribe returns word-level timestamps suitable for the editor's subtitle burn-in pipeline. See the [ElevenLabs Speech-to-Text API](https://elevenlabs.io/docs/api-reference/speech-to-text/convert) for current model details.

When an approved edit plan requests captions and no transcript exists, the UI starts the configured transcription job, waits for its word timestamps, then applies the caption operation. A missing transcript no longer produces fake “Clip [start-end]” overlays that look like subtitles.

Reviewed plans apply supported edits and report skipped parts when a request mixes supported and unsupported capabilities. An actual execution failure still rolls the plan back atomically. Unsupported capabilities and needed clarifications remain explicit in the preview. The direct instruction API uses the same local-AI planner in `auto`/`ollama` mode; deterministic parser-only behavior is used only in explicit `rules` mode or as the visible fallback when `auto` cannot reach Ollama.

---

## Starting the Application

### Option A: Local Serving (Uvicorn)

```bash
.\.venv-work\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Once running:
- **Interactive UI:** Open [http://localhost:8000](http://localhost:8000) in your browser.
- **OpenAPI Interactive Documentation:** Visit [http://localhost:8000/docs](http://localhost:8000/docs).
- **Service Health Check:** [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health).
- **Service Readiness Check:** [http://localhost:8000/api/v1/ready](http://localhost:8000/api/v1/ready).
- The **Quality**, **FPS**, and **Speed** controls beside **Render MP4** set H.264 quality (CRF 16–26), output frame rate (24–60 FPS), and encoding preset for that render. Codec and output folder remain server-managed.

### Retrying API writes safely

Every write request under `/api/v1/` requires an `Idempotency-Key` header. Reuse the same key only when retrying the exact same request; the service returns the original response instead of repeating the edit or job. Reusing a key with a different payload returns `409 Conflict`. The browser UI generates a fresh key for each write automatically.

```http
POST /api/v1/projects
Idempotency-Key: create-project-unique-request-id
Content-Type: application/json
```

### Option B: Docker Compose

```bash
docker-compose up --build
```
The Docker container automatically provisions Debian Linux, installs FFmpeg with libass and FreeType fonts, initializes SQLite storage, runs health checks, and binds to port `8000`.

---

## Running Automated Tests

Run the complete automated suite (unit, API, real FFmpeg rendering, storyboard workflow, voice-over, and session cases):

```bash
.\.venv-work\Scripts\python.exe -m pytest -v
```

To run a specific test category:
```bash
# Unit tests
.\.venv-work\Scripts\python.exe -m pytest tests/unit/ -v

# Integration tests (API & real FFmpeg rendering)
.\.venv-work\Scripts\python.exe -m pytest tests/integration/ -v

# End-to-end tests (determinism & sample sessions)
.\.venv-work\Scripts\python.exe -m pytest tests/e2e/ -v
```

Measure local Ollama planning latency with cold parse-cache requests on synthetic 5-minute and 60-minute transcripts (transcription and rendering are excluded):

```bash
.\.venv-work\Scripts\python.exe scripts/benchmark_planning_latency.py --runs 5 --output docs/latency_benchmark.json
```

The report records median and slowest response time per duration. The checked-in one-run sample is preliminary and currently exceeds the assessment's 3-second target; rerun with multiple samples on the intended review hardware before making a scale claim.

---

## Using the CLI Session Runner

The command-line session runner executes YAML or JSON session configurations sequentially using the real engine and asserts expected outcomes.

```bash
# Run single cut session
python session_runner.py sessions/session_01_single_cut.yaml

# Run ambiguity & clarification session
python session_runner.py sessions/session_04_ambiguity_clarification.yaml

# Run full render session
python session_runner.py sessions/session_15_full_render.yaml -o results.json
```

---

## Editing Workflow Guide

### 1. Upload Video
- **UI:** Drag and drop an MP4 or MOV file into the dropzone.
- **API:** `POST /api/v1/media/upload` with `multipart/form-data`.
- The engine calculates original media SHA-256 hash, probes stream metadata, and establishes Revision 0.

### 2. Supply or Generate Transcript
- **Upload:** `POST /api/v1/transcript/{media_id}/upload` with word-level JSON (`id`, `text`, `start`, `end`, `speaker`).
- **Auto-Generate:** `POST /api/v1/transcript/{media_id}/generate` uses local `faster-whisper` when installed. External Google speech recognition fallback is disabled unless `GOOGLE_SPEECH_FALLBACK_ENABLED=true` is explicitly set.

### 3. Submit Natural-Language Instructions
- **Supported Operations:**
  - Cut range: `"cut from 00:02 to 00:05"`
  - Keep range: `"keep only from 00:05 to 00:15"`
  - Remove phrase: `"remove phrase 'welcome to'"`
  - Speed change: `"speed up from 00:00 to 00:05 by 1.5x"`
  - Mute: `"mute word 'confidential'"` or `"mute from 00:01 to 00:03"`
  - Bleep: `"bleep from 00:02 to 00:04"` (1kHz tone)
  - Noise reduction: `"remove background noise"`, `"reduce wind noise"`, or `"clean up audio"`
  - Rotate/mirror: `"rotate video 90 degrees clockwise"`, `"mirror horizontally"`, or `"flip video vertically"`
  - Anchored Caption: `"caption 'Important' at 'goodbye'"`
  - Generate Captions: `"generate captions"`
  - Filler words: `"remove filler words"`
  - Silence: `"remove silence longer than 1.0s"`
  - Reorder: `"reorder segments seg_0002, seg_0001"`
  - Undo: `"undo"`
  - Redo: `"redo"`
  - Targeted Restore: `"restore revision 1"` or `"restore edit op_1234"`

### 4. Resolving Clarifications
When an instruction is ambiguous (e.g. repeated phrase), the response returns status `needs_clarification` with options:
```json
{
  "status": "needs_clarification",
  "clarification_question": "The phrase 'welcome to' appears 2 times...",
  "options": [
    {"id": "opt_1", "label": "Occurrence 1: at 0.50s - 1.10s (Speaker A)"},
    {"id": "opt_2", "label": "Occurrence 2: at 8.00s - 8.60s (Speaker B)"}
  ]
}
```
Resolve by posting `{"session_id": "...", "selected_option_id": "opt_1"}` to `/api/v1/instruction/clarify`.

### 5. Render & Download
- Click **Render Video** in the UI or call `POST /api/v1/render/{media_id}`.
- FFmpeg compiles trims, concatenations, ASS subtitles, and audio effects.
- Output duration and original media hash are verified with FFprobe.
- Download the final verified MP4 via the download button or `GET /api/v1/render/download/{filename}`.

---

## Troubleshooting

- **`ffmpeg: command not found`:**
  Ensure FFmpeg is installed and on your system `PATH`. On Windows, run `winget install Gyan.FFmpeg.Essentials`. On Debian/Ubuntu, run `sudo apt-get install ffmpeg`. Alternatively, set `FFMPEG_BINARY` in `.env`.
- **Readiness check says `not_ready`:**
  Visit `/api/v1/ready` to view the diagnostic payload. It confirms if FFmpeg, FFprobe, and writable storage directories are reachable.
- **Port already in use:**
  Change `APP_PORT=8080` in `.env`.
