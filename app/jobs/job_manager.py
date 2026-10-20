import concurrent.futures
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from app.models.db import JobRecord, SessionLocal
from app.models.render import JobStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)


class JobManager:
    """Manages asynchronous long-running background tasks with status polling and SQLite persistence."""

    def __init__(self, max_workers: int = 4):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._futures: Dict[str, concurrent.futures.Future] = {}
        self._cancel_callbacks: Dict[str, Callable[[], None]] = {}
        self._lock = threading.Lock()

    def submit_job(
        self,
        job_type: str,
        task_fn: Callable[..., Any],
        *args,
        **kwargs,
    ) -> str:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        # Record in memory
        with self._lock:
            self._memory_cache[job_id] = {
                "job_id": job_id,
                "job_type": job_type,
                "status": JobStatus.QUEUED.value,
                "progress": 0.0,
                "result": None,
                "error": None,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }

        # Persist in DB
        db = SessionLocal()
        try:
            db_job = JobRecord(
                job_id=job_id,
                job_type=job_type,
                status=JobStatus.QUEUED.value,
                progress=0.0,
            )
            db.add(db_job)
            db.commit()
        finally:
            db.close()

        def _runner():
            with self._lock:
                if self._memory_cache.get(job_id, {}).get("status") == JobStatus.CANCELLED.value:
                    return
            self._update_status(job_id, JobStatus.RUNNING.value, progress=10.0)
            try:
                res = task_fn(*args, **kwargs)
                with self._lock:
                    cancelled = self._memory_cache.get(job_id, {}).get("status") == JobStatus.CANCELLED.value
                if not cancelled:
                    self._update_status(job_id, JobStatus.COMPLETED.value, progress=100.0, result=res)
            except Exception as e:
                with self._lock:
                    cancelled = self._memory_cache.get(job_id, {}).get("status") == JobStatus.CANCELLED.value
                if cancelled:
                    return
                logger.error(f"Job {job_id} failed: {str(e)}", exc_info=True)
                self._update_status(job_id, JobStatus.FAILED.value, progress=100.0, error=str(e))

        future = self.executor.submit(_runner)
        with self._lock:
            self._futures[job_id] = future
        return job_id

    def register_cancel_callback(self, job_id: str, callback: Callable[[], None]) -> None:
        """Register an interrupt for the currently running task, if it is still active."""
        with self._lock:
            item = self._memory_cache.get(job_id)
            if item and item["status"] in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
                self._cancel_callbacks[job_id] = callback

    def cancel_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        callback = None
        with self._lock:
            item = self._memory_cache.get(job_id)
            if item is None:
                return None
            if item["status"] in (JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value):
                return dict(item)
            item["status"] = JobStatus.CANCELLED.value
            item["error"] = "Job cancelled by user"
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            callback = self._cancel_callbacks.pop(job_id, None)
            future = self._futures.get(job_id)
        if future:
            future.cancel()
        if callback:
            try:
                callback()
            except Exception:
                logger.exception("Failed to interrupt cancelled job %s", job_id)
        self._update_status(job_id, JobStatus.CANCELLED.value, error="Job cancelled by user")
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            if job_id in self._memory_cache:
                return dict(self._memory_cache[job_id])

        db = SessionLocal()
        try:
            record = db.query(JobRecord).filter(JobRecord.job_id == job_id).first()
            if not record:
                return None
            res_dict = json.loads(record.result_json) if record.result_json else None
            return {
                "job_id": record.job_id,
                "job_type": record.job_type,
                "status": record.status,
                "progress": record.progress,
                "result": res_dict,
                "error": record.error_message,
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            }
        finally:
            db.close()

    def _update_status(
        self,
        job_id: str,
        status: str,
        progress: float = 0.0,
        result: Any = None,
        error: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        res_json = None
        if result is not None:
            if hasattr(result, "model_dump"):
                result = result.model_dump()
            res_json = json.dumps(result)

        with self._lock:
            if job_id in self._memory_cache:
                if (
                    self._memory_cache[job_id].get("status") == JobStatus.CANCELLED.value
                    and status != JobStatus.CANCELLED.value
                ):
                    return
                self._memory_cache[job_id]["status"] = status
                self._memory_cache[job_id]["progress"] = progress
                if result is not None:
                    self._memory_cache[job_id]["result"] = result
                if error:
                    self._memory_cache[job_id]["error"] = error
                self._memory_cache[job_id]["updated_at"] = now.isoformat()

        db = SessionLocal()
        try:
            rec = db.query(JobRecord).filter(JobRecord.job_id == job_id).first()
            if rec:
                rec.status = status
                rec.progress = progress
                if res_json:
                    rec.result_json = res_json
                if error:
                    rec.error_message = error
                rec.updated_at = now
                db.commit()
        finally:
            db.close()


# Global singleton
job_manager = JobManager()
