# Sources, Licenses, and Provenance

The default local planner model documented for this application is Qwen2.5 1.5B (Apache-2.0). Model weights selected by users through `OLLAMA_MODEL` have separate licenses and must be reviewed independently before commercial use; in particular, Qwen2.5 3B is under the Qwen Research License Agreement.

---

## 1. Core Libraries & Backend Dependencies

| Library | Version | License | Source / Repository | Purpose |
|---|---|---|---|---|
| **Python** | 3.11.9 | PSF License | python.org | Core runtime environment |
| **FastAPI** | 0.136.0 | MIT | github.com/tiangolo/fastapi | REST API framework |
| **Pydantic** | 2.13.3 | MIT | github.com/pydantic/pydantic | Request/response validation & schemas |
| **Pydantic-Settings** | 2.14.2 | MIT | github.com/pydantic/pydantic-settings | Environment variable management |
| **Uvicorn** | 0.46.0 | BSD-3-Clause | github.com/encode/uvicorn | ASGI web server |
| **SQLAlchemy** | 2.0.51 | MIT | sqlalchemy.org | Persistent database ORM |
| **jsonschema** | 4.26.0 | MIT | github.com/python-jsonschema/jsonschema | Timeline Draft 2020-12 validation |
| **PyYAML** | 6.0.3 | MIT | github.com/yaml/pyyaml | YAML parser for session files |
| **pytest** | 8.4.2 | MIT | pytest.org | Automated test suite runner |
| **httpx** | 0.28.1 | BSD-3-Clause | github.com/encode/httpx | HTTP test client and API client |
| **NumPy** | 2.4.6 | BSD-3-Clause | numpy.org | Numerical processing & audio analysis |
| **SciPy** | 1.15.3 | BSD-3-Clause | scipy.org | Signal processing |

---

## 2. Optional Local AI Model

| Model | Version / size | License | Source | Purpose |
|---|---|---|---|---|
| **Qwen2.5 1.5B** | `qwen2.5:1.5b` (Ollama quantized build) | Apache-2.0 for the 1.5B model weights | [Official Ollama model page](https://ollama.com/library/qwen2.5) | Optional local prompt-to-edit-plan adapter |

The 3B variant is not used as the default: its model page identifies a Qwen Research License Agreement, which restricts use to research/evaluation unless separately licensed. Model licenses are distinct from the Ollama server software license.

## 3. Media Processing Tools

| Tool | Version | License | Source / Repository | Purpose |
|---|---|---|---|---|
| **FFmpeg** | 9.0.2 (Gyan Essentials, project-local build) | GPL v3 / LGPL v3 components; verify the selected build's configuration before redistribution | [FFmpeg Windows download options](https://ffmpeg.org/download.html) / [Gyan release builds](https://www.gyan.dev/ffmpeg/builds/) | Audio/video trimming, concatenation, filter graphs |
| **FFprobe** | 9.0.2 (distributed in the same Gyan Essentials archive) | GPL v3 / LGPL v3 components; verify the selected build's configuration before redistribution | [FFmpeg Windows download options](https://ffmpeg.org/download.html) / [Gyan release builds](https://www.gyan.dev/ffmpeg/builds/) | Media stream inspection, duration, codec verification |

The local archive was SHA-256 verified against the publisher's checksum before extraction (`4705843ccaaf54257c16ad90f3e952ece33c17df964ecf7bfdbb0f49c7171077`). The extracted binaries live under `tools/ffmpeg/bin/` and are ignored by Git; they are an environment install, not a vendored dependency. FFmpeg build licensing is configuration-dependent. Review the included license notices and applicable FFmpeg obligations before redistributing the binaries or using this exact build in a commercial deployment.
| **libass** | Bundled in FFmpeg | ISC License | github.com/libass/libass | Subtitle renderer for ASS caption formatting |
| **FreeType** | Bundled in FFmpeg | FTL / GPL v2 | freetype.org | Font rasterization for text overlays |

---

## 4. Typography & Fonts

| Font | License | Source | Purpose |
|---|---|---|---|
| **Plus Jakarta Sans** | SIL Open Font License 1.1 | Google Fonts | Primary UI typography |
| **JetBrains Mono** | SIL Open Font License 1.1 | Google Fonts | Monospace font for hashes and durations |
| **Arial / DejaVu** | Free / Permissive | System fonts / DejaVu Fonts | Subtitle font for ASS captions and overlays |

---

## 5. Test Fixtures & Media

| Asset | Origin | License / Provenance |
|---|---|---|
| `sample_with_audio.mp4` | Generated programmatically via FFmpeg `lavfi` (`testsrc2` + `sine=440`) | Public Domain / CC0 (Synthetically generated) |
| `sample_no_audio.mp4` | Generated programmatically via FFmpeg `lavfi` (`testsrc2`) | Public Domain / CC0 (Synthetically generated) |
| `sample_transcript.json` | Deterministic JSON fixture created for this project | MIT / CC0 |
| `corrupt_media.mp4` | Synthetic corrupt byte stream | Public Domain / CC0 |

No copyrighted or proprietary third-party video footage or audio recordings are included in this repository. All test media are generated deterministically by `scripts/generate_fixtures.py`.
