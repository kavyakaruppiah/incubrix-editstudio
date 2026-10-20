# Assessment hard-case regression evidence

Run the focused deterministic suite from the repository root:

```powershell
.venv-work\Scripts\python.exe -m pytest tests/assessment/test_submission_hard_cases.py -q --junitxml=docs/hard_case_test_results.xml
```

**Focused result (20 October 2026): 7 passed.** The machine-readable JUnit result is in [`hard_case_test_results.xml`](hard_case_test_results.xml); scenario code is in [`test_submission_hard_cases.py`](../tests/assessment/test_submission_hard_cases.py).

## What the scenarios establish

| Case | Verified behavior | Scope and remaining evidence |
|---|---|---|
| 1 | Word-anchored caption survives a cut/restore sequence through timeline revision restore. | Deterministic engine-level test; not a separate encoded-video inspection. |
| 2 | A reordered timeline can retain background music and a bleep; filler removal removes the filler source interval, and the removed interval no longer maps into rendered output. | Synthetic transcript/timeline fixture; not a real multi-speaker recording render. |
| 3 | “80 seconds,” “a minute twenty,” and “the last 10 seconds” parse; an out-of-range time is rejected; repeating a completed source cut is rejected without advancing revision. | The test checks time-range validation, not the full natural-language caption-at-5:00 API path. |
| 4 | Undoing the latest cut restores duration while preserving background music that existed before the cut. | The requested second-to-last-cut targeting behavior is not implemented or verified; undo remains latest-active-operation based. |
| 5 | Four occurrences of “thanks” produce four clarification choices; each choice carries a cut-after-the-selected-word range, and one choice executes while preserving the selected word. | Parser/engine fixture evidence; not a live UI clarification interaction. The parser now recognizes “remove everything after I say …”. |
| 6 | 10x speed is accepted, whole-video cuts are rejected, and rejected cuts do not advance revision. | The combined three-part feasible/impossible instruction and its all-or-report behavior still need a dedicated plan-level test. |
| 7 | Overlapping transcript words produce a warning; VFR metadata and speaker labels are carried by the timeline model. | Synthetic metadata only. A VFR phone recording, diarization label-swap detection, overlap warning in the UI, and render behavior are not verified here. |

## Full-suite result

The full repository run completed with **392 passed and 1 failed**. The failure was `session_15_full_render.yaml`: its real FFmpeg render exceeded the renderer's 120-second timeout on this machine. It is recorded as a render-timeout failure, not as a passing assessment scenario. Re-run that render on the target deployment environment and retain its output and verification manifest before claiming it passes.
