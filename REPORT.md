# Engineering Assessment Report: Prompt-Based Video Editing Engine

## 1. Executive Summary

This report documents the architectural design, formal data models, deterministic execution pipeline, time policies, rendering engine, and empirical verification of the containerised, prompt-based video editing engine.

The engine accepts raw video assets (MP4, MOV), interprets natural-language editing instructions, calculates content-anchored output positions, maintains an immutable history of reversible edits, serialises canonical timelines with cryptographic SHA-256 integrity, renders verified output through FFmpeg, and provides structured results for every interaction.

---

## 2. System Architecture

The engine follows a modular, layer-isolated design:

```
+-------------------------------------------------------------------------+
|                               Browser UI                                |
|   (Source Player, Waveform/Timeline Visualizer, Word Chips, History)   |
+------------------------------------+------------------------------------+
                                     | HTTP / JSON (OpenAPI 3.1)
+------------------------------------v------------------------------------+
|                             FastAPI API                                 |
|  (/api/v1/health, /ready, /media, /transcript, /timeline, /instruction) |
+------------------+-----------------------------+------------------------+
                   |                             |
+------------------v--------------+   +----------v------------------------+
|   Natural Language Pipeline     |   |          Job Manager              |
|  - Pattern Registry             |   |  - Thread pool background tasks   |
|  - Ambiguity & Multi-match      |   |  - SQLite persistence             |
|  - 3-Way Outcome Resolution     |   |  - Status polling (queued/running)|
+------------------+--------------+   +----------+------------------------+
                   |                             |
+------------------v-----------------------------v------------------------+
|                      Deterministic Timeline Engine                      |
|  - Segment interval mathematics & reordering                            |
|  - Source-to-Output mapping & Word anchoring                            |
|  - Snapshots, Undo, Redo, Targeted Restore                              |
|  - JSON Schema Draft 2020-12 validation & Canonical SHA-256 Hashing    |
+------------------------------------+------------------------------------+
                                     |
+------------------------------------v------------------------------------+
|                       FFmpeg Rendering Subsystem                        |
|  - filter_complex generation (trim, atrim, concat, atempo, volume, ass)|
|  - Post-render verification & probe                                     |
|  - Output duration check & Original media SHA-256 preservation          |
+-------------------------------------------------------------------------+
```

### Module Boundaries:
- `app/engine/`: Core deterministic timeline mutation logic, canonical hashing, snapping, and undo/redo history.
- `app/api/`: Versioned REST endpoints under `/api/v1` with idempotency and correlation ID middleware.
- `app/rendering/`: Real FFmpeg filter compilation, execution, probe inspection, and manifest generation.
- `app/storage/`: Clean storage adapter abstraction (`LocalStorageAdapter`, `S3StorageAdapter`).
- `app/transcription/`: Word-level transcription adapter interface (`FasterWhisperAdapter`, `FixtureTranscriptionAdapter`).
- `app/jobs/`: Asynchronous background task runner for renders and transcriptions.

---

## 3. Timeline Data Model & Time Policy

### 3.1 Formal Segment Model
The timeline represents the output video as an ordered sequence of contiguous output segments $S = [s_0, s_1, \dots, s_{n-1}]$. Each segment $s_i$ refers directly to a source-media interval:
$$s_i = (\text{source\_start}_i, \text{source\_end}_i, \text{speed}_i, \text{audio\_enabled}_i, \text{video\_enabled}_i)$$

Output duration for segment $s_i$ is derived as:
$$\text{duration\_output}_i = \frac{\text{source\_end}_i - \text{source\_start}_i}{\text{speed}_i}$$

Output start and end times for segment $s_i$ are:
$$\text{output\_start}_i = \sum_{k=0}^{i-1} \text{duration\_output}_k$$
$$\text{output\_end}_i = \text{output\_start}_i + \text{duration\_output}_i$$

Total timeline duration is $\text{output\_end}_{n-1}$.

### 3.2 Time Policies Documented
1. **Source Time ($t_{\text{src}}$):**
   Fixed, immutable time coordinate relative to the start of the original uploaded video asset ($0 \le t_{\text{src}} \le \text{duration}_{\text{source}}$).
2. **Current Timeline Time ($t_{\text{tl}}$):**
   Derived output time coordinate across retained segments.
3. **Speed Convention:**
   Playback speed multiplier $v > 0$. When $v > 1.0$, content is accelerated, reducing output duration. When $v < 1.0$, content is slowed down, extending output duration. Video presentation timestamps are scaled by $1/v$, and audio streams pass through chained `atempo` filters.

### 3.3 Source-to-Output Mapping
Given any source timestamp $t_{\text{src}}$:
$$\text{output\_times}(t_{\text{src}}) = \left\{ \text{output\_start}_i + \frac{t_{\text{src}} - \text{source\_start}_i}{\text{speed}_i} \;\middle|\; s_i \in S, \;\text{source\_start}_i \le t_{\text{src}} \le \text{source\_end}_i \right\}$$
- If content has been cut, $\text{output\_times}(t_{\text{src}}) = \emptyset$.
- If content is retained in a single segment, it yields a single output timestamp.
- If content is duplicated or looped across multiple segments, it maps to multiple distinct output timestamps.

### 3.4 Content Anchoring (Captions & Effects)
Captions anchor directly to persistent word IDs ($w_1, w_2, \dots, w_k$). The engine maps the words' source interval $[\min(w.\text{start}), \max(w.\text{end})]$ through the active segment list.
- **Anchored:** If words remain intact in the timeline, their output times are recalculated automatically after cuts, speed modifications, and reordering.
- **Removed:** If words are cut, the anchor resolves to status `"removed"`. Captions referencing removed words are excluded from rendering and surfaced with explicit warnings.

---

## 4. Determinism & Canonical Timeline Hashing

Section 2.12 requires that identical inputs, transcripts, configurations, and instruction sequences produce the exact same canonical timeline hash.

### Canonical Serialization Rules:
1. Volatile and runtime-dependent fields are excluded:
   `{"created_at", "updated_at", "job_id", "correlation_id", "rendered_outputs", "warnings", "operation_id", "segment_id", "media_id"}`.
2. Dictionary keys are sorted lexicographically at every depth.
3. Whitespace is stripped (`separators=(',', ':')`).
4. Floating-point numbers are rounded to 6 decimal places with $-0.0$ normalised to $0.0$.
5. The canonical string is encoded to UTF-8 bytes and hashed with SHA-256.

Empirical verification (Scenario 27 & 28) confirms that multiple runs across different processes produce the exact identical 64-character hex digest.

---

## 5. Natural-Language Parsing & 3-Way Outcome Contract

Every natural-language instruction returns exactly one outcome:
1. `applied`: Valid, unambiguous instruction committed to the timeline.
2. `needs_clarification`: Ambiguous target (e.g. repeated phrase without ordinal or speaker) with structured, numbered options.
3. `rejected`: Invalid range, unsupported operation, or semantic conflict.

### Ambiguity Handling:
When a phrase (such as *"welcome to"*) appears multiple times:
- If qualified (e.g. *"remove the first 'welcome to'"* or *"spoken by Speaker B"*), the parser immediately resolves the target occurrence.
- If unqualified, the engine returns `needs_clarification` with options detailing:
  - Stable option ID (`opt_1`, `opt_2`).
  - Text snippet with surrounding context.
  - Timestamps and speaker identity.
  - Pre-computed execution payload.
- Resolving the choice against `/api/v1/instruction/clarify` atomically commits the disambiguated edit.

---

## 6. Real FFmpeg Rendering & Verification

Rendering compiles the timeline into a safe FFmpeg `filter_complex` execution array without shell interpolation.

### Filter Generation:
- Video Trims: `[0:v]trim=start=S:end=E,setpts=PTS-STARTPTS[v0_raw]; [v0_raw]setpts=PTS/SPEED[v0]`
- Audio Trims: `[0:a]atrim=start=S:end=E,asetpts=PTS-STARTPTS[a0_raw]; [a0_raw]atempo=...[a0]`
- Concatenation: `[v0][v1]concat=n=N:v=1:a=0[v_concat]`
- Captions: Compiled into ASS subtitles and burned via `ass` filter (utilizing libass).
- Text Overlays: Positioned with `drawtext` filter.
- Audio Effects: `volume=enable='between(...)':volume=0` for mutes; `sine` generator mixed via `amix` for audible 1kHz bleeps.
- Constant Frame Rate Defense: `fps=30` filter applied to normalize variable-frame-rate inputs.

### Post-Render Verification:
After rendering, FFprobe measures the output:
- Readability of video and audio streams.
- Measured duration compared against expected timeline duration (tolerance $\pm 0.15$s).
- Original media SHA-256 re-computed to guarantee source file immutability.

---

## 7. Known Limitations & Future Work

1. **Local Diarization:** Faster-whisper does not include built-in speaker diarization without pyannote; speaker IDs default to null unless supplied in uploaded transcripts.
2. **GPU Acceleration:** Rendering currently uses CPU-based `libx264` and `aac`. NVENC / QuickSync can be added via `.env` configuration.
3. **Complex Transitions:** Only hard cuts and speed changes are implemented; cross-fades and dissolves are slated for future releases.
