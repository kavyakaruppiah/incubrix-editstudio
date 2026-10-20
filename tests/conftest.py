import pytest
from fastapi.testclient import TestClient

from app.config import settings


@pytest.fixture(autouse=True)
def disable_local_model_fallbacks_for_tests(monkeypatch):
    """Keep unit/integration tests isolated from models configured in a developer .env."""
    monkeypatch.setattr(settings, "OLLAMA_FALLBACK_MODELS", "")
    original_request = TestClient.request

    def request_with_idempotency_key(self, method, url, *args, **kwargs):
        if str(url).startswith("/api/v1/") and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers = dict(kwargs.get("headers") or {})
            if not any(name.lower() == "idempotency-key" for name in headers):
                import uuid
                headers["Idempotency-Key"] = f"test_{uuid.uuid4().hex}"
            kwargs["headers"] = headers
        return original_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "request", request_with_idempotency_key)
