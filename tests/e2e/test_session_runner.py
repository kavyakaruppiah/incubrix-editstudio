import json
from pathlib import Path
from app.services.session_service import execute_session, load_session_file

REPO_ROOT = Path(__file__).parent.parent.parent
SESSION_FILE = REPO_ROOT / "sessions" / "session_01_single_cut.yaml"


def test_28_three_repeated_executions_determinism(tmp_path):
    """Scenario 28: Three repeated executions of the exact same session produce identical hashes."""
    data = load_session_file(SESSION_FILE)

    hashes = []
    durations = []
    for i in range(3):
        out_file = tmp_path / f"results_run_{i}.json"
        res = execute_session(data, output_results_path=str(out_file))
        hashes.append(res["final_timeline_hash"])
        durations.append(res["final_duration_s"])

    # All three runs must produce the exact same canonical timeline hash
    assert hashes[0] == hashes[1] == hashes[2]
    assert durations[0] == durations[1] == durations[2]


def test_36_session_runner_result_generation(tmp_path):
    """Scenario 36: Complete result JSON generation from session runner."""
    out_file = tmp_path / "test_results.json"
    data = load_session_file(SESSION_FILE)
    res = execute_session(data, output_results_path=str(out_file))

    assert out_file.is_file()
    saved_data = json.loads(out_file.read_text(encoding="utf-8"))

    assert "media_id" in saved_data
    assert "original_media_hash" in saved_data
    assert "initial_timeline_hash" in saved_data
    assert "final_timeline_hash" in saved_data
    assert "final_revision" in saved_data
    assert "results" in saved_data
    assert len(saved_data["results"]) == 1
    assert saved_data["results"][0]["result"]["status"] == "applied"
