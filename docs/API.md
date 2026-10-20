# API contract and error responses

The service exposes `/api/v1/*` through FastAPI and publishes an OpenAPI 3.1.0
document. `openapi.yaml` is generated from `app.main:app`; the contract test
loads that file and compares it with the running application's generated schema.

All framework-level errors use this envelope:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Media was not found",
    "retryable": false,
    "details": null
  }
}
```

The API also returns the request's `X-Correlation-Id` response header. Error
codes currently emitted by the common handlers are `BAD_REQUEST`,
`UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `PAYLOAD_TOO_LARGE`,
`VALIDATION_ERROR`, `RATE_LIMITED`, `HTTP_ERROR`, and `INTERNAL_ERROR`.
Instruction outcomes are domain responses with exactly one status:
`applied`, `needs_clarification`, or `rejected`.

`Idempotency-Key` records are stored in the database. Repeating a completed
request with the same key and payload replays its saved response. Reusing the
key with a different payload returns `CONFLICT`; a matching request that is
still running receives a conflict response instead of executing a duplicate.
Stale pending claims expire after ten minutes and can be retried.
