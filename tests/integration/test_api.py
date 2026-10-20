import time
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.utils.idempotency import IdempotencyStore

client = TestClient(app)
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_37_health_and_readiness():
    """Scenario 37: Health and readiness endpoints."""
    # Health
    res_h = client.get("/api/v1/health")
    assert res_h.status_code == 200
    assert res_h.json()["status"] == "ok"

    # Readiness
    res_r = client.get("/api/v1/ready")
    assert res_r.status_code == 200
    data = res_r.json()
    assert "status" in data
    assert "ffmpeg_available" in data
    assert "storage_writable" in data
    assert data["ffmpeg_available"] is True
    assert data["storage_writable"] is True


def test_33_idempotent_api_requests(monkeypatch):
    """Scenario 33: Idempotency keys prevent duplicate operations and reject payload mutation."""
    # This contract test should remain deterministic even when a local model is installed.
    from app.services import plan_service as plan_service_module
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "rules")
    # 1. Upload media
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    with open(source_path, "rb") as f:
        up_res = client.post("/api/v1/media/upload", files={"file": ("sample.mp4", f, "video/mp4")})
    assert up_res.status_code == 200
    media_id = up_res.json()["media_id"]

    idempotency_key = f"idemp_test_key_{uuid.uuid4().hex}"
    payload = {"instruction": "cut from 00:01 to 00:03"}

    # Initial request
    res1 = client.post(
        f"/api/v1/instruction/{media_id}",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "applied"

    # Retried request with identical key and payload -> returns cached result
    res2 = client.post(
        f"/api/v1/instruction/{media_id}",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert res2.status_code == 200
    assert res2.json()["operation_id"] == data1["operation_id"]

    # Reused key with DIFFERENT payload -> 409 Conflict
    diff_payload = {"instruction": "cut from 00:05 to 00:08"}
    res3 = client.post(
        f"/api/v1/instruction/{media_id}",
        json=diff_payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert res3.status_code == 409
    assert res3.json()["error"]["code"] == "CONFLICT"


def test_idempotency_ledger_persists_pending_cache_and_conflict_states():
    store = IdempotencyStore()
    key = f"ledger-test-{uuid.uuid4().hex}"
    payload = {"instruction": "cut 1 to 2", "media_id": "sample"}

    assert store.check(key, payload)[0] == "new"
    assert store.check(key, payload)[0] == "pending"
    store.save(key, payload, 200, {"status": "applied"})
    state, cached = store.check(key, payload)
    assert state == "cached"
    assert cached.response_data == {"status": "applied"}
    assert store.check(key, {"instruction": "cut 2 to 3"})[0] == "conflict"


def test_project_creation_is_idempotent_with_retries():
    key = f"project-create-{uuid.uuid4().hex}"
    payload = {"name": "Idempotency retry project", "description": "one create only"}

    first = client.post(
        "/api/v1/projects", json=payload, headers={"Idempotency-Key": key}
    )
    second = client.post(
        "/api/v1/projects", json=payload, headers={"Idempotency-Key": key}
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["project_id"] == second.json()["project_id"]

    conflict = client.post(
        "/api/v1/projects",
        json={"name": "Different payload"},
        headers={"Idempotency-Key": key},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "CONFLICT"


def test_api_write_without_idempotency_key_is_rejected():
    raw_client = TestClient(app)
    response = raw_client.post(
        "/api/v1/projects",
        json={"name": "must not create"},
        headers={"Idempotency-Key": ""},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_transcript_upload_idempotency_uses_content_and_media_identity():
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    transcript_path = FIXTURES_DIR / "sample_transcript.json"
    with source_path.open("rb") as source:
        uploaded = client.post(
            "/api/v1/media/upload",
            files={"file": ("transcript_retry_source.mp4", source, "video/mp4")},
        )
    assert uploaded.status_code == 200
    media_id = uploaded.json()["media_id"]
    transcript_bytes = transcript_path.read_bytes()
    key = f"transcript-upload-{uuid.uuid4().hex}"

    first = client.post(
        f"/api/v1/transcript/{media_id}/upload",
        files={"file": ("transcript.json", transcript_bytes, "application/json")},
        headers={"Idempotency-Key": key},
    )
    second = client.post(
        f"/api/v1/transcript/{media_id}/upload",
        files={"file": ("transcript.json", transcript_bytes, "application/json")},
        headers={"Idempotency-Key": key},
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "uploaded"


def test_timeline_exports_source_linked_otio_json():
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    with source_path.open("rb") as source:
        uploaded = client.post(
            "/api/v1/media/upload",
            files={"file": ("otio_export_source.mp4", source, "video/mp4")},
        )
    assert uploaded.status_code == 200
    media_id = uploaded.json()["media_id"]

    response = client.get(f"/api/v1/timeline/{media_id}/export/otio")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.opentimelineio+json")
    assert f'filename="{media_id}.otio"' in response.headers["content-disposition"]
    document = response.json()
    assert document["OTIO_SCHEMA"] == "Timeline.1"
    tracks = document["tracks"]["children"]
    assert [track["kind"] for track in tracks] == ["Video", "Audio"]
    video_clip = tracks[0]["children"][0]
    assert video_clip["OTIO_SCHEMA"] == "Clip.2"
    assert video_clip["media_reference"]["OTIO_SCHEMA"] == "ExternalReference.1"
    assert video_clip["media_reference"]["target_url"].startswith("file:")
    assert video_clip["source_range"]["duration"]["value"] > 0


def test_34_async_job_status_transitions():
    """Scenario 34: Async job transitions from queued/running to completed."""
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    with open(source_path, "rb") as f:
        up_res = client.post("/api/v1/media/upload", files={"file": ("sample_async.mp4", f, "video/mp4")})
    media_id = up_res.json()["media_id"]

    render_res = client.post(f"/api/v1/render/{media_id}")
    assert render_res.status_code == 200
    job_id = render_res.json()["job_id"]

    # Poll until completed or timeout
    max_wait = 30
    start = time.time()
    final_status = None
    while time.time() - start < max_wait:
        st_res = client.get(f"/api/v1/render/status/{job_id}")
        assert st_res.status_code == 200
        job_data = st_res.json()
        final_status = job_data["status"]
        if final_status in ("completed", "failed"):
            break
        time.sleep(0.5)

    assert final_status == "completed"


def test_35_api_error_response_consistency():
    """Scenario 35: API error response format consistency across endpoints."""
    # Non-existent media GET
    res404 = client.get("/api/v1/media/non_existent_id")
    assert res404.status_code == 404
    assert res404.json()["error"]["code"] == "NOT_FOUND"
    assert set(res404.json()["error"]) == {"code", "message", "retryable", "details"}

    # Invalid file upload
    corrupt_path = FIXTURES_DIR / "corrupt_media.mp4"
    with open(corrupt_path, "rb") as f:
        res_bad = client.post("/api/v1/media/upload", files={"file": ("corrupt.mp4", f, "video/mp4")})
    assert res_bad.status_code == 400
    assert res_bad.json()["error"]["code"] == "BAD_REQUEST"
    assert isinstance(res_bad.json()["error"]["message"], str)


def test_render_rejects_out_of_range_export_options():
    response = client.post("/api/v1/render/unknown-media", json={"quality": 99, "frame_rate": 30})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_timeline_reorder_endpoint_persists_clip_order(monkeypatch):
    """Timeline drag reorder applies through the public API and is persisted."""
    from app.services import plan_service as plan_service_module
    monkeypatch.setattr(plan_service_module.settings, "INSTRUCTION_PROVIDER", "rules")
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    with source_path.open("rb") as source_file:
        upload_res = client.post(
            "/api/v1/media/upload",
            files={"file": ("reorder_sample.mp4", source_file, "video/mp4")},
        )
    assert upload_res.status_code == 200
    media_id = upload_res.json()["media_id"]

    edit_res = client.post(f"/api/v1/instruction/{media_id}", json={"instruction": "cut from 00:01 to 00:03"})
    assert edit_res.status_code == 200
    timeline_res = client.get(f"/api/v1/timeline/{media_id}")
    assert timeline_res.status_code == 200
    original_ids = [clip["segment_id"] for clip in timeline_res.json()["clips"]]
    assert len(original_ids) >= 2
    reordered_ids = list(reversed(original_ids))

    reorder_res = client.post(
        f"/api/v1/timeline/{media_id}/reorder",
        json={"segment_ids": reordered_ids},
    )
    assert reorder_res.status_code == 200, reorder_res.text
    assert reorder_res.json()["status"] == "applied"

    persisted_res = client.get(f"/api/v1/timeline/{media_id}")
    assert [clip["segment_id"] for clip in persisted_res.json()["clips"]] == reordered_ids


def test_caption_style_studio_endpoint_saves_renderable_ass_style():
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    with source_path.open("rb") as source_file:
        upload_res = client.post(
            "/api/v1/media/upload",
            files={"file": ("caption_style_sample.mp4", source_file, "video/mp4")},
        )
    assert upload_res.status_code == 200
    media_id = upload_res.json()["media_id"]

    style_res = client.post(
        f"/api/v1/caption-style/{media_id}",
        json={
            "font_family": "Arial",
            "font_size": 32,
            "text_color": "#F0A020",
            "outline_color": "#102030",
            "outline_width": 3,
            "shadow_offset": 2,
            "background_box": True,
            "background_color": "#08090A",
            "vertical_position": "middle",
        },
    )
    assert style_res.status_code == 200, style_res.text
    style = style_res.json()["style"]
    assert style["font_name"] == "Arial"
    assert style["font_size"] == 32
    assert style["primary_color"] == "&H0020A0F0"
    assert style["outline_color"] == "&H00302010"
    assert style["border_style"] == 3
    assert style["position"] == "center"
    assert style["alignment"] == 5

    persisted = client.get(f"/api/v1/timeline/{media_id}")
    assert persisted.json()["global_caption_style"]["primary_color"] == "&H0020A0F0"


def test_project_reopens_uploaded_source_for_browser_preview():
    """Projects retain a playable source reference across page reloads."""
    project_res = client.post("/api/v1/projects", json={"name": "Preview persistence"})
    assert project_res.status_code == 200
    project_id = project_res.json()["id"]

    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    source_bytes = source_path.read_bytes()
    with source_path.open("rb") as source_file:
        upload_res = client.post(
            "/api/v1/media/upload",
            files={"file": ("preview_source.mp4", source_file, "video/mp4")},
        )
    assert upload_res.status_code == 200
    media_id = upload_res.json()["media_id"]

    update_res = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"media_id": media_id, "name": "Saved preview"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Saved preview"

    project = client.get(f"/api/v1/projects/{project_id}").json()
    assert project["media"]["media_id"] == media_id

    source_res = client.get(f"/api/v1/media/{media_id}/source")
    assert source_res.status_code == 200
    assert source_res.content == source_bytes

    duplicate_res = client.post(f"/api/v1/projects/{project_id}/duplicate")
    assert duplicate_res.status_code == 200
    duplicate_id = duplicate_res.json()["id"]
    duplicate_data = client.get(f"/api/v1/projects/{duplicate_id}").json()
    assert duplicate_data["media"]["media_id"] == media_id

    delete_res = client.delete(f"/api/v1/projects/{project_id}")
    assert delete_res.status_code == 200
    assert client.get(f"/api/v1/projects/{project_id}").status_code == 404
    assert client.get(f"/api/v1/media/{media_id}/source").content == source_bytes
