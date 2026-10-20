import time
import uuid
import hashlib
import json
import re
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_v1_router
from app.config import settings
from app.models.db import init_db
from app.utils.logger import get_logger
from app.utils.idempotency import idempotency_store

logger = get_logger("app.main")

# Initialize database tables
init_db()

app = FastAPI(
    title="IncuBrix EditStudio",
    description="Professional AI-assisted video editing studio with reversible prompt-based editing, captions, effects, timeline verification, and FFmpeg rendering.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details=None,
    retryable: bool = False,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": details,
        }},
        headers={"X-Correlation-Id": getattr(request.state, "correlation_id", "")},
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    status_codes = {
        400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN",
        404: "NOT_FOUND", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE",
        422: "VALIDATION_ERROR", 429: "RATE_LIMITED",
    }
    detail = exc.detail
    message = detail if isinstance(detail, str) else "Request could not be completed"
    details = None if isinstance(detail, str) else detail
    return _error_response(
        request, exc.status_code, status_codes.get(exc.status_code, "HTTP_ERROR"),
        message, details, retryable=exc.status_code == 429 or exc.status_code >= 500,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        request, 422, "VALIDATION_ERROR", "Request validation failed",
        details=exc.errors(), retryable=False,
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled request error", extra={"correlation_id": getattr(request.state, "correlation_id", None)}, exc_info=exc)
    return _error_response(
        request, 500, "INTERNAL_ERROR", "An unexpected server error occurred",
        retryable=True,
    )

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{settings.APP_PORT}",
        f"http://127.0.0.1:{settings.APP_PORT}",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_and_logging_middleware(request: Request, call_next):
    # Correlation ID
    correlation_id = request.headers.get("X-Correlation-Id") or f"corr_{uuid.uuid4().hex[:10]}"
    request.state.correlation_id = correlation_id

    start_time = time.perf_counter()
    try:
        # Older high-volume endpoints already hash their parsed payloads inside
        # the route. Cover the remaining JSON write endpoints centrally so
        # retries cannot repeat edits, project creation, or job submission.
        method = request.method.upper()
        path = request.url.path
        key = request.headers.get("Idempotency-Key", "").strip()
        content_type = request.headers.get("content-type", "").lower()
        is_api_write = path.startswith("/api/v1/") and method in {"POST", "PUT", "PATCH", "DELETE"}
        if is_api_write and not key:
            return JSONResponse(
                status_code=400,
                content={"error": {
                    "code": "IDEMPOTENCY_KEY_REQUIRED",
                    "message": "Write requests under /api/v1 require an Idempotency-Key header.",
                    "retryable": False,
                    "details": None,
                }},
                headers={"X-Correlation-Id": correlation_id},
            )
        manually_idempotent = (
            path == "/api/v1/media/upload"
            or path == "/api/v1/instruction/clarify"
            or bool(re.fullmatch(r"/api/v1/transcript/[^/]+/upload", path))
            or bool(re.fullmatch(r"/api/v1/instruction/[^/]+", path))
            or bool(re.fullmatch(r"/api/v1/timeline/[^/]+/(?:undo|redo|restore)", path))
            or bool(re.fullmatch(r"/api/v1/render/[^/]+", path))
        )
        idempotency_payload = None
        should_cache = (
            key
            and method in {"POST", "PUT", "PATCH", "DELETE"}
            and not manually_idempotent
            and "multipart/form-data" not in content_type
            and "application/octet-stream" not in content_type
        )
        if should_cache:
            raw_body = await request.body()
            try:
                request_body = json.loads(raw_body) if raw_body else None
            except (json.JSONDecodeError, UnicodeDecodeError):
                request_body = {"sha256": hashlib.sha256(raw_body).hexdigest()}
            idempotency_payload = {
                "method": method,
                "path": path,
                "query": request.url.query,
                "body": request_body,
            }
            state, record = idempotency_store.check(key, idempotency_payload)
            if state == "cached" and record:
                response = JSONResponse(
                    status_code=record.status_code or 200,
                    content=record.response_data,
                    headers={
                        "X-Correlation-Id": correlation_id,
                        "X-Process-Time": f"{time.perf_counter() - start_time:.4f}s",
                    },
                )
                return response
            if state in {"conflict", "pending"}:
                return JSONResponse(
                    status_code=409,
                    content={"error": {
                        "code": "CONFLICT",
                        "message": (
                            "Idempotency key reuse with a different request payload is rejected."
                            if state == "conflict"
                            else "An identical request with this idempotency key is still in progress."
                        ),
                        "retryable": state == "pending",
                        "details": None,
                    }},
                    headers={"X-Correlation-Id": correlation_id},
                )

        response: Response = await call_next(request)
        if should_cache and idempotency_payload is not None:
            response_content_type = response.headers.get("content-type", "").lower()
            if "application/json" in response_content_type:
                body = b"".join([chunk async for chunk in response.body_iterator])
                try:
                    response_data = json.loads(body.decode("utf-8"))
                    idempotency_store.save(key, idempotency_payload, response.status_code, response_data)
                    clean_headers = {
                        name: value for name, value in response.headers.items()
                        if name.lower() not in {"content-length", "content-type", "transfer-encoding"}
                    }
                    clean_headers["X-Correlation-Id"] = correlation_id
                    clean_headers["X-Process-Time"] = f"{time.perf_counter() - start_time:.4f}s"
                    return JSONResponse(
                        status_code=response.status_code,
                        content=response_data,
                        headers=clean_headers,
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    idempotency_store.delete(key)
            else:
                idempotency_store.delete(key)
        process_time = time.perf_counter() - start_time
        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Process-Time"] = f"{process_time:.4f}s"
        return response
    except Exception as e:
        process_time = time.perf_counter() - start_time
        logger.error(
            f"Unhandled exception during {request.method} {request.url.path}: {str(e)}",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        raise e


# Mount API Router
app.include_router(api_v1_router)

# Keep retry safety visible in the live OpenAPI contract for every write route.
_fastapi_openapi = app.openapi


def _openapi_with_idempotency_header():
    if app.openapi_schema:
        return app.openapi_schema
    schema = _fastapi_openapi()
    for path_item in schema.get("paths", {}).values():
        for method, operation in path_item.items():
            if method.lower() not in {"post", "put", "patch", "delete"} or not isinstance(operation, dict):
                continue
            parameters = operation.setdefault("parameters", [])
            idempotency_parameter = next((
                parameter for parameter in parameters
                if parameter.get("in") == "header" and parameter.get("name", "").lower() == "idempotency-key"
            ), None)
            if idempotency_parameter:
                idempotency_parameter["required"] = True
            else:
                parameters.append({
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": True,
                    "description": "Unique key used to safely retry this write request.",
                    "schema": {"type": "string"},
                })
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_idempotency_header

# Mount Frontend static files
frontend_dir = Path(__file__).parent.parent / "frontend"
frontend_dir.mkdir(parents=True, exist_ok=True)


@app.get("/")
def serve_index():
    index_file = frontend_dir / "index.html"
    if index_file.is_file():
        return FileResponse(str(index_file))
    return {"message": "IncuBrix EditStudio API. Visit /docs for OpenAPI documentation or /api/v1/health."}


if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
