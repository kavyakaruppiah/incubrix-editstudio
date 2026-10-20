from pathlib import Path

import yaml

from app.main import app


def test_checked_in_openapi_matches_live_fastapi_schema():
    openapi_path = Path(__file__).resolve().parents[2] / "openapi.yaml"
    saved = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))
    live = app.openapi()

    assert live["openapi"] == "3.1.0"
    assert saved == live
    for path_item in live["paths"].values():
        for method, operation in path_item.items():
            if method.lower() in {"post", "put", "patch", "delete"}:
                assert any(
                    parameter.get("in") == "header"
                    and parameter.get("name") == "Idempotency-Key"
                    and parameter.get("required") is True
                    for parameter in operation.get("parameters", [])
                )
