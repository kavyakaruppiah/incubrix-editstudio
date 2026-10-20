import pytest
import json
from pathlib import Path
from app.services.session_service import execute_session, load_session_file

REPO_ROOT = Path(__file__).parent.parent.parent
SESSIONS_DIR = REPO_ROOT / "sessions"

SESSION_FILES = sorted(list(SESSIONS_DIR.glob("*.yaml")))


@pytest.mark.parametrize("session_file", SESSION_FILES, ids=[f.name for f in SESSION_FILES])
def test_all_pack_sessions(session_file, tmp_path):
    """Run every scripted session three times and verify deterministic outputs."""
    data = load_session_file(session_file)
    runs = []
    for run_index in range(3):
        out_results = tmp_path / f"{session_file.stem}_run_{run_index + 1}_results.json"
        result = execute_session(data, output_results_path=str(out_results))
        assert result is not None
        assert "final_timeline_hash" in result
        assert out_results.is_file()
        persisted = json.loads(out_results.read_text(encoding="utf-8"))
        assert len(persisted["results"]) == len(data["instructions"])
        for step in persisted["results"]:
            assert step["result"]["status"] in {"applied", "needs_clarification", "rejected"}
            assert "timeline_hash" in step["result"]
            assert "duration_s" in step["result"]
        runs.append(result)

    assert len({run["final_timeline_hash"] for run in runs}) == 1, f"Nondeterministic timeline in {session_file.name}"
    assert len({round(run["final_duration_s"], 9) for run in runs}) == 1, f"Nondeterministic duration in {session_file.name}"
