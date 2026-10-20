import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.transcription.audio_extractor import extract_voice_audio
from app.transcription.unified_transcriber import unified_transcriber
from app.services.instruction_service import instruction_service
from app.services.media_service import media_service
from app.services.timeline_service import timeline_service

client = TestClient(app)
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_hidden_case_1_voice_audio_extraction_and_speech_transcription():
    """Hidden Test Case 1: Extract 16kHz mono voice audio from video and transcribe accurately."""
    sample_video = FIXTURES_DIR / "sample_with_audio.mp4"
    assert sample_video.is_file()

    # 1. Voice audio extraction
    wav_path = extract_voice_audio(sample_video, filter_noise=True)
    assert wav_path is not None
    assert wav_path.is_file()
    assert wav_path.stat().st_size > 1000

    # 2. Transcription
    transcript = unified_transcriber.transcribe(str(sample_video))
    assert transcript is not None
    assert isinstance(transcript.words, list)
    if transcript.words:
        assert transcript.words[0].id.startswith("w_")
        assert transcript.words[0].start >= 0.0
        assert transcript.words[0].end > transcript.words[0].start


def test_hidden_case_2_video_without_audio_stream_resilience():
    """Hidden Test Case 2: Video without audio stream must not crash, returning empty transcript cleanly."""
    no_audio_video = FIXTURES_DIR / "sample_no_audio.mp4"
    assert no_audio_video.is_file()

    # Audio extractor should cleanly detect absence of audio stream and return None
    wav_path = extract_voice_audio(no_audio_video)
    assert wav_path is None

    # Transcriber should return empty Transcript without raising an exception
    transcript = unified_transcriber.transcribe(str(no_audio_video))
    assert transcript is not None
    assert len(transcript.words) == 0


def test_hidden_case_3_silent_or_low_energy_audio_resilience():
    """Hidden Test Case 3: Silent or low-energy audio handled gracefully with noise filtering."""
    # Test audio extraction with filtering
    sample_video = FIXTURES_DIR / "sample_with_audio.mp4"
    wav_clean = extract_voice_audio(sample_video, filter_noise=True)
    assert wav_clean is not None
    assert wav_clean.suffix.lower() == ".wav"


def test_hidden_case_4_async_transcription_api_lifecycle():
    """Hidden Test Case 4: Asynchronous API transcription trigger and job completion lifecycle."""
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    with open(source_path, "rb") as f:
        up_res = client.post("/api/v1/media/upload", files={"file": ("hidden_test_media.mp4", f, "video/mp4")})
    assert up_res.status_code == 200
    media_id = up_res.json()["media_id"]

    # Trigger transcription
    gen_res = client.post(f"/api/v1/transcript/{media_id}/generate")
    assert gen_res.status_code == 200
    job_id = gen_res.json()["job_id"]
    assert job_id is not None

    # Poll status until completed
    max_wait = 20
    start = time.time()
    final_status = None
    while time.time() - start < max_wait:
        st_res = client.get(f"/api/v1/transcript/status/{job_id}")
        assert st_res.status_code == 200
        data = st_res.json()
        final_status = data["status"]
        if final_status in ("completed", "failed"):
            break
        time.sleep(0.5)

    assert final_status == "completed"

    # Verify timeline updated
    tl_res = client.get(f"/api/v1/timeline/{media_id}")
    assert tl_res.status_code == 200
    tl_data = tl_res.json()
    assert "transcript" in tl_data


def test_hidden_case_5_transcript_driven_editing_operations():
    """Hidden Test Case 5: Edit operations based on extracted transcript words execute seamlessly."""
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    with open(source_path, "rb") as f:
        up_res = client.post("/api/v1/media/upload", files={"file": ("hidden_edit_media.mp4", f, "video/mp4")})
    media_id = up_res.json()["media_id"]

    # Load sample transcript to simulate extracted words
    load_res = client.post(f"/api/v1/transcript/{media_id}/load_sample")
    assert load_res.status_code == 200

    # 1. Edit: Cut phrase
    res_cut = instruction_service.process_instruction(media_id, "cut the first phrase 'welcome to'")
    assert res_cut.status.value == "applied"

    # 2. Edit: Remove filler words
    res_filler = instruction_service.process_instruction(media_id, "remove filler words")
    assert res_filler.status.value == "applied"

    # 3. Edit: Generate captions
    res_cap = instruction_service.process_instruction(media_id, "generate captions")
    assert res_cap.status.value == "applied"

    # 4. Verify resulting timeline
    final_tl = timeline_service.get_timeline(media_id)
    assert final_tl.revision >= 3
    assert len(final_tl.captions) > 0
    assert final_tl.total_output_duration < final_tl.source_metadata.duration
