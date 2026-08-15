"""Small, persistent worker queue used by the optional reliable sync engine."""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional

from .task_store import PendingJob, TaskStore


class SyncEngine:
    """Run durable file jobs with bounded in-memory scheduling and classified retries."""

    RETRY_DELAYS = (15, 300, 3600)

    def __init__(self, store: TaskStore, handler: Callable[[PendingJob], dict], workers: int = 3, max_queue: int = 20000, completion: Optional[Callable[[PendingJob, dict], None]] = None):
        self.store = store
        self.handler = handler
        self.workers = max(1, min(int(workers), 8))
        self.completion = completion
        self._queue: queue.Queue[Optional[PendingJob]] = queue.Queue(maxsize=max(100, int(max_queue)))
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        # Scheduled jobs include both the bounded in-memory queue and jobs
        # currently being handled. Only the latter are reported as inflight.
        self._scheduled: set[int] = set()
        self._active: set[int] = set()
        self._lock = threading.RLock()

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        self.pump()
        for index in range(self.workers):
            thread = threading.Thread(target=self._worker, name=f"cloudstrm-worker-{index + 1}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def enqueue(self, monitor_root: str, path: str, action: str = "sync", old_path: str = "", payload: Optional[dict] = None, delay: float = 0) -> bool:
        created = self.store.enqueue(monitor_root, path, action, old_path, payload, delay)
        self.pump()
        return created

    def pump(self) -> int:
        moved = 0
        with self._lock:
            capacity = max(0, self._queue.maxsize - self._queue.qsize())
            for job in self.store.claim_ready(min(capacity, 500)):
                if job.id in self._scheduled:
                    continue
                try:
                    self._queue.put_nowait(job)
                except queue.Full:
                    break
                self._scheduled.add(job.id)
                moved += 1
        return moved

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "memory_queued": self._queue.qsize(),
                "inflight": len(self._active),
                "scheduled": len(self._scheduled),
                "workers": len(self._threads),
            }

    def stop(self, timeout: float = 20) -> bool:
        # Keep workers alive while draining work already accepted into memory.
        self._stop.set()
        deadline = time.monotonic() + max(0, timeout)
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.1)
        for _ in self._threads:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                break
        for thread in self._threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        stopped = all(not thread.is_alive() for thread in self._threads)
        if not stopped:
            return False
        self._threads = []
        with self._lock:
            self._scheduled.clear()
            self._active.clear()
        return True

    def _worker(self) -> None:
        while True:
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                if self._stop.is_set():
                    return
                self.pump()
                continue
            if job is None:
                self._queue.task_done()
                return
            with self._lock:
                self._active.add(job.id)
            try:
                result = self.handler(job) or {}
                status = result.get("status", "processed")
                if status in {"failed", "unstable"} and self._retryable(result):
                    if job.attempts < len(self.RETRY_DELAYS):
                        self.store.retry_job(job, str(result.get("reason") or status), self.RETRY_DELAYS[job.attempts], result.get("diagnosis") or {"actual_target": result.get("actual_target", "")})
                    else:
                        self.store.fail_job(job, str(result.get("reason") or status), result.get("diagnosis") or {"actual_target": result.get("actual_target", "")})
                        self._complete(job, {"status": "failed", "reason": str(result.get("reason") or status)})
                elif status == "failed":
                    self.store.fail_job(job, str(result.get("reason") or "同步失败"), result.get("diagnosis") or {"actual_target": result.get("actual_target", "")})
                    self._complete(job, result)
                else:
                    self.store.remove_job(job.id)
                    self.store.resolve_failure(job.monitor_root, job.path, job.action)
                    self._complete(job, result)
            except Exception as exc:
                if job.attempts < len(self.RETRY_DELAYS):
                    self.store.retry_job(job, str(exc), self.RETRY_DELAYS[job.attempts], {"actual_target": job.payload.get("actual_target", "")})
                else:
                    self.store.fail_job(job, str(exc), {"actual_target": job.payload.get("actual_target", "")})
                    self._complete(job, {"status": "failed", "reason": str(exc)})
            finally:
                with self._lock:
                    self._active.discard(job.id)
                    self._scheduled.discard(job.id)
                self._queue.task_done()
                self.pump()

    @staticmethod
    def _retryable(result: dict) -> bool:
        if result.get("retryable") is not None:
            return bool(result["retryable"])
        status = result.get("status")
        return status == "unstable" or any(token in str(result.get("reason") or "").lower() for token in ("i/o", "tempor", "timeout", "stale"))

    def _complete(self, job: PendingJob, result: dict) -> None:
        if self.completion:
            self.completion(job, result)
