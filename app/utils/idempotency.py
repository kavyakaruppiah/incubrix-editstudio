import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from app.models.db import IdempotencyRecord as DBIdempotencyRecord, SessionLocal


class IdempotencyRecord:
    def __init__(self, key: str, payload_hash: str, status_code: int | None, response_data: Dict[str, Any], state: str = "completed"):
        self.key = key
        self.payload_hash = payload_hash
        self.status_code = status_code
        self.response_data = response_data
        self.state = state


class IdempotencyStore:
    """Database-backed idempotency ledger with a short pending-request lease."""

    PENDING_LEASE = timedelta(minutes=10)

    def __init__(self):
        self._lock = threading.RLock()

    @staticmethod
    def hash_payload(data: Any) -> str:
        """Deterministically hash the request payload structure."""
        if data is None:
            encoded = b""
        else:
            encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _view(record: DBIdempotencyRecord) -> IdempotencyRecord:
        response = json.loads(record.response_json) if record.response_json else {}
        return IdempotencyRecord(
            record.key, record.payload_hash, record.status_code, response, record.state
        )

    def check(self, key: str, payload: Any) -> Tuple[str, Optional[IdempotencyRecord]]:
        """Return ``new``, ``pending``, ``cached``, or ``conflict`` for a key."""
        payload_hash = self.hash_payload(payload)
        now = datetime.now(timezone.utc)
        with self._lock:
            db = SessionLocal()
            try:
                record = db.query(DBIdempotencyRecord).filter(DBIdempotencyRecord.key == key).first()
                if record is None:
                    record = DBIdempotencyRecord(
                        key=key, payload_hash=payload_hash, state="pending",
                        created_at=now, updated_at=now,
                    )
                    db.add(record)
                    try:
                        db.commit()
                        return "new", None
                    except IntegrityError:
                        db.rollback()
                        record = db.query(DBIdempotencyRecord).filter(DBIdempotencyRecord.key == key).first()
                        if record is None:
                            raise

                if record.payload_hash != payload_hash:
                    return "conflict", self._view(record)

                updated_at = record.updated_at
                if updated_at and updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                if record.state == "pending":
                    if updated_at and now - updated_at > self.PENDING_LEASE:
                        record.created_at = now
                        record.updated_at = now
                        db.commit()
                        return "new", None
                    return "pending", self._view(record)

                return "cached", self._view(record)
            finally:
                db.close()

    def save(self, key: str, payload: Any, status_code: int, response_data: Dict[str, Any]) -> None:
        """Complete a previously claimed key with its exact response payload."""
        payload_hash = self.hash_payload(payload)
        now = datetime.now(timezone.utc)
        with self._lock:
            db = SessionLocal()
            try:
                record = db.query(DBIdempotencyRecord).filter(DBIdempotencyRecord.key == key).first()
                if record is None:
                    record = DBIdempotencyRecord(key=key, payload_hash=payload_hash, created_at=now)
                    db.add(record)
                elif record.payload_hash != payload_hash:
                    raise ValueError("idempotency key is already claimed by a different request")
                record.state = "completed"
                record.status_code = status_code
                record.response_json = json.dumps(response_data, sort_keys=True, separators=(",", ":"), default=str)
                record.updated_at = now
                db.commit()
            finally:
                db.close()

    def delete(self, key: str) -> None:
        """Release a pending claim after an endpoint fails before producing a result."""
        db = SessionLocal()
        try:
            db.query(DBIdempotencyRecord).filter(
                DBIdempotencyRecord.key == key,
                DBIdempotencyRecord.state == "pending",
            ).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


idempotency_store = IdempotencyStore()
