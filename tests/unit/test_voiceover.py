import io
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.models.transcript import TranscriptWord
from app.services.document_service import DocumentService
from app.services.script_aligner import ScriptAligner
from app.services.voiceover_service import voiceover_service

client = TestClient(app)
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_document_service_text_extraction():
    service = DocumentService()

    # 1. Plain text extraction
    txt_content = b"Welcome to our video presentation on automated editing."
    res_txt = service.extract_text(txt_content, "script.txt")
    assert "Welcome to our video presentation" in res_txt

    # 2. DOCX extraction
    import docx
    doc_io = io.BytesIO()
    doc = docx.Document()
    doc.add_paragraph("This is the official voiceover script from Word.")
    doc.save(doc_io)
    doc_io.seek(0)
    res_docx = service.extract_text(doc_io.getvalue(), "script.docx")
    assert "This is the official voiceover script from Word." in res_docx

    # 3. PDF extraction
    from pypdf import PdfWriter
    pdf_io = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    # Write empty / basic page
    writer.write(pdf_io)
    # Test unsupported extension rejection
    with pytest.raises(Exception):
        service.extract_text(b"some content", "file.xyz")


def test_script_aligner_audio_sync():
    aligner = ScriptAligner()
    # Reference audio words
    audio_words = [
        TranscriptWord(id="w1", text="Hello", start=0.5, end=0.9),
        TranscriptWord(id="w2", text="and", start=0.9, end=1.1),
        TranscriptWord(id="w3", text="welcome", start=1.1, end=1.6),
        TranscriptWord(id="w4", text="everyone", start=1.6, end=2.2),
    ]

    # Script text matching audio
    script = "Hello and welcome everyone!"
    aligned = aligner.align_script_to_audio(script, audio_words, media_duration=10.0)

    assert len(aligned.words) == 4
    assert aligned.words[0].text == "Hello"
    assert aligned.words[0].start == 0.5
    assert aligned.words[0].end == 0.9
    assert aligned.words[2].text == "welcome"
    assert aligned.words[2].start == 1.1

    # Script text with slight insertion/variation
    script_extra = "Hello and warmly welcome everyone today"
    aligned_extra = aligner.align_script_to_audio(script_extra, audio_words, media_duration=10.0)
    assert len(aligned_extra.words) == 6
    # Verify timestamps are strictly monotonic
    for i in range(1, len(aligned_extra.words)):
        assert aligned_extra.words[i].start >= aligned_extra.words[i - 1].start
        assert aligned_extra.words[i].end >= aligned_extra.words[i].start


def test_voiceover_api_upload_and_alignment():
    """Test full voiceover upload via API with a DOCX voice-over file."""
    # 1. Upload sample video
    source_path = FIXTURES_DIR / "sample_with_audio.mp4"
    with open(source_path, "rb") as f:
        up_res = client.post("/api/v1/media/upload", files={"file": ("sample_vo.mp4", f, "video/mp4")})
    assert up_res.status_code == 200
    media_id = up_res.json()["media_id"]

    # 2. Create sample voice-over DOCX file
    import docx
    doc_io = io.BytesIO()
    doc = docx.Document()
    doc.add_paragraph("Hello and welcome to the show um this is speaker A speaking today.")
    doc.save(doc_io)
    doc_bytes = doc_io.getvalue()

    # 3. Upload voice-over document via API
    vo_res = client.post(
        f"/api/v1/voiceover/{media_id}/upload?auto_align=true&auto_captions=true",
        files={"file": ("voiceover_script.docx", doc_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert vo_res.status_code == 200
    data = vo_res.json()
    assert data["status"] == "aligned"
    assert data["word_count"] > 5
    assert data["captions_generated"] > 0

    # 4. Verify timeline has aligned transcript and captions
    tl_res = client.get(f"/api/v1/timeline/{media_id}")
    assert tl_res.status_code == 200
    timeline = tl_res.json()
    assert len(timeline["transcript"]["words"]) == data["word_count"]
    assert len(timeline["captions"]) > 0
    # First word starts around 0.1 - 0.5s matching video audio
    first_word = timeline["transcript"]["words"][0]
    assert first_word["text"] == "Hello"
    assert first_word["start"] < 1.0
