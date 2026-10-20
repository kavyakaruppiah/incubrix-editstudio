import threading
import time

from app.jobs import job_manager as job_manager_module
from app.jobs.job_manager import JobManager


class _FakeQuery:
    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return None


class _FakeSession:
    def add(self, _record):
        pass

    def commit(self):
        pass

    def close(self):
        pass

    def query(self, *_args, **_kwargs):
        return _FakeQuery()


def test_running_job_cancellation_interrupts_task_and_stays_cancelled(monkeypatch):
    monkeypatch.setattr(job_manager_module, "SessionLocal", _FakeSession)
    manager = JobManager(max_workers=1)
    started = threading.Event()
    interrupted = threading.Event()

    def long_task():
        started.set()
        interrupted.wait(timeout=3)
        return {"should_not_complete": True}

    try:
        job_id = manager.submit_job("render", long_task)
        assert started.wait(timeout=2)
        manager.register_cancel_callback(job_id, interrupted.set)

        result = manager.cancel_job(job_id)
        assert result["status"] == "cancelled"
        assert interrupted.wait(timeout=1)
        time.sleep(0.02)
        assert manager.get_job(job_id)["status"] == "cancelled"
        assert manager.get_job(job_id)["result"] is None
    finally:
        manager.executor.shutdown(wait=True, cancel_futures=True)


def test_queued_job_can_be_cancelled_before_it_starts(monkeypatch):
    monkeypatch.setattr(job_manager_module, "SessionLocal", _FakeSession)
    manager = JobManager(max_workers=1)
    blocker = threading.Event()
    entered = threading.Event()
    queued_ran = threading.Event()

    try:
        manager.submit_job("blocker", lambda: (entered.set(), blocker.wait(timeout=3)))
        assert entered.wait(timeout=2)
        queued_job = manager.submit_job("render", queued_ran.set)
        result = manager.cancel_job(queued_job)
        blocker.set()
        assert result["status"] == "cancelled"
        assert not queued_ran.wait(timeout=0.1)
        assert manager.get_job(queued_job)["status"] == "cancelled"
    finally:
        blocker.set()
        manager.executor.shutdown(wait=True, cancel_futures=True)
