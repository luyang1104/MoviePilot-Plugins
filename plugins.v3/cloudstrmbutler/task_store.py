"""Persistent task, failure, and cleanup state for reliable STRM synchronization."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class PendingJob:
    id: int
    monitor_root: str
    path: str
    action: str
    old_path: str
    attempts: int
    available_at: float
    payload: dict


class TaskStore:
    """SQLite store for resumable work. Successful file state stays in SyncStateStore."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._migrate()

    def _migrate(self) -> None:
        self._conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = self._conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        current = int(row["version"]) if row else 0
        if current < 1:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    monitor_root TEXT NOT NULL,
                    path TEXT NOT NULL,
                    action TEXT NOT NULL,
                    old_path TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(monitor_root, path, action)
                );
                CREATE INDEX IF NOT EXISTS idx_pending_jobs_ready ON pending_jobs(available_at, id);
                CREATE TABLE IF NOT EXISTS task_runs (
                    run_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    monitor_root TEXT,
                    status TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    queued INTEGER NOT NULL DEFAULT 0,
                    processed INTEGER NOT NULL DEFAULT 0,
                    unchanged INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_task_runs_started ON task_runs(started_at DESC);
                CREATE TABLE IF NOT EXISTS task_failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    monitor_root TEXT NOT NULL,
                    path TEXT NOT NULL,
                    action TEXT NOT NULL,
                    error TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    resolved_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_failures_open ON task_failures(resolved_at, updated_at DESC);
                CREATE TABLE IF NOT EXISTS cleanup_batches (
                    batch_id TEXT PRIMARY KEY,
                    monitor_root TEXT NOT NULL,
                    status TEXT NOT NULL,
                    paths TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    confirmed_at REAL
                );
                """
            )
            if row:
                self._conn.execute("UPDATE schema_version SET version = 1")
            else:
                self._conn.execute("INSERT INTO schema_version(version) VALUES (1)")
        self._conn.commit()

    def enqueue(self, monitor_root: str, path: str, action: str, old_path: str = "", payload: Optional[dict] = None, delay: float = 0) -> bool:
        now = time.time()
        ready = now + max(0, delay)
        encoded = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            existing = self._conn.execute(
                "SELECT id FROM pending_jobs WHERE monitor_root = ? AND path = ? AND action = ?",
                (monitor_root, path, action),
            ).fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE pending_jobs SET old_path = ?, payload = ?, available_at = MIN(available_at, ?), updated_at = ? WHERE id = ?",
                    (old_path or "", encoded, ready, now, existing["id"]),
                )
                self._conn.commit()
                return False
            self._conn.execute(
                "INSERT INTO pending_jobs(monitor_root,path,action,old_path,available_at,payload,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (monitor_root, path, action, old_path or "", ready, encoded, now, now),
            )
            self._conn.commit()
            return True

    def claim_ready(self, limit: int = 100) -> List[PendingJob]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM pending_jobs WHERE available_at <= ? ORDER BY available_at, id LIMIT ?",
                (time.time(), max(1, limit)),
            ).fetchall()
        return [self._job(row) for row in rows]

    def remove_job(self, job_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM pending_jobs WHERE id = ?", (job_id,))
            self._conn.commit()

    def retry_job(self, job: PendingJob, error: str, delay: float) -> None:
        now = time.time()
        attempts = job.attempts + 1
        with self._lock:
            self._conn.execute(
                "UPDATE pending_jobs SET attempts = ?, available_at = ?, updated_at = ? WHERE id = ?",
                (attempts, now + delay, now, job.id),
            )
            self._upsert_failure(job.monitor_root, job.path, job.action, error, attempts, now)
            self._conn.commit()

    def fail_job(self, job: PendingJob, error: str) -> None:
        now = time.time()
        with self._lock:
            self._upsert_failure(job.monitor_root, job.path, job.action, error, job.attempts + 1, now)
            self._conn.execute("DELETE FROM pending_jobs WHERE id = ?", (job.id,))
            self._conn.commit()

    def resolve_failure(self, monitor_root: str, path: str, action: str) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE task_failures SET resolved_at = ?, updated_at = ? WHERE monitor_root = ? AND path = ? AND action = ? AND resolved_at IS NULL",
                (now, now, monitor_root, path, action),
            )
            self._conn.commit()

    def _upsert_failure(self, root: str, path: str, action: str, error: str, attempts: int, now: float) -> None:
        row = self._conn.execute(
            "SELECT id FROM task_failures WHERE monitor_root = ? AND path = ? AND action = ? AND resolved_at IS NULL",
            (root, path, action),
        ).fetchone()
        if row:
            self._conn.execute(
                "UPDATE task_failures SET error = ?, attempts = ?, updated_at = ? WHERE id = ?",
                (error[:2000], attempts, now, row["id"]),
            )
        else:
            self._conn.execute(
                "INSERT INTO task_failures(monitor_root,path,action,error,attempts,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (root, path, action, error[:2000], attempts, now, now),
            )

    def start_run(self, kind: str, monitor_root: Optional[str] = None) -> str:
        run_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO task_runs(run_id,kind,monitor_root,status,started_at) VALUES(?,?,?,?,?)",
                (run_id, kind, monitor_root, "running", time.time()),
            )
            self._conn.commit()
        return run_id

    def update_run(self, run_id: str, **counts: int) -> None:
        allowed = {key: int(value) for key, value in counts.items() if key in {"queued", "processed", "unchanged", "failed", "deleted"}}
        if not allowed:
            return
        columns = ", ".join(f"{key} = {key} + ?" for key in allowed)
        with self._lock:
            self._conn.execute(f"UPDATE task_runs SET {columns} WHERE run_id = ?", (*allowed.values(), run_id))
            self._conn.commit()

    def finish_run(self, run_id: str, status: str = "completed", message: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE task_runs SET status = ?, finished_at = ?, message = ? WHERE run_id = ?",
                (status, time.time(), message[:1000], run_id),
            )
            self._conn.commit()

    def finish_run_if_settled(self, run_id: str) -> bool:
        """Finish a queued run only after every accepted job reached a terminal result."""
        with self._lock:
            row = self._conn.execute(
                "SELECT queued, processed, unchanged, failed, status FROM task_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if not row or row["status"] != "running":
                return False
            completed = int(row["processed"]) + int(row["unchanged"]) + int(row["failed"])
            if completed < int(row["queued"]):
                return False
            self._conn.execute(
                "UPDATE task_runs SET status = 'completed', finished_at = ? WHERE run_id = ?",
                (time.time(), run_id),
            )
            self._conn.commit()
            return True

    def create_cleanup_batch(self, monitor_root: str, paths: Iterable[str], ttl_seconds: int = 7 * 86400) -> Optional[str]:
        unique_paths = sorted({str(path) for path in paths if path})
        if not unique_paths:
            return None
        batch_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO cleanup_batches(batch_id,monitor_root,status,paths,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                (batch_id, monitor_root, "pending", json.dumps(unique_paths, ensure_ascii=False), now, now + ttl_seconds),
            )
            self._conn.commit()
        return batch_id

    def claim_cleanup_batch(self, batch_id: str) -> Optional[List[str]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT paths FROM cleanup_batches WHERE batch_id = ? AND status = 'pending' AND (expires_at IS NULL OR expires_at > ?)",
                (batch_id, time.time()),
            ).fetchone()
            if not row:
                return None
            self._conn.execute("UPDATE cleanup_batches SET status = 'confirmed', confirmed_at = ? WHERE batch_id = ?", (time.time(), batch_id))
            self._conn.commit()
        return list(json.loads(row["paths"]))

    def status(self) -> dict:
        with self._lock:
            queued = self._conn.execute("SELECT COUNT(*) FROM pending_jobs").fetchone()[0]
            running = self._conn.execute("SELECT * FROM task_runs WHERE status = 'running' ORDER BY started_at DESC").fetchall()
            latest = self._conn.execute("SELECT * FROM task_runs ORDER BY started_at DESC LIMIT 20").fetchall()
            pending_cleanup = self._conn.execute("SELECT batch_id,monitor_root,paths,created_at,expires_at FROM cleanup_batches WHERE status = 'pending' AND (expires_at IS NULL OR expires_at > ?) ORDER BY created_at DESC", (time.time(),)).fetchall()
        return {
            "queued": queued,
            "running": [dict(row) for row in running],
            "recent_runs": [dict(row) for row in latest],
            "cleanup_batches": [{**dict(row), "path_count": len(json.loads(row["paths"]))} for row in pending_cleanup],
        }

    def failures(self, limit: int = 100, include_resolved: bool = False) -> List[dict]:
        query = "SELECT * FROM task_failures"
        if not include_resolved:
            query += " WHERE resolved_at IS NULL"
        query += " ORDER BY updated_at DESC LIMIT ?"
        with self._lock:
            return [dict(row) for row in self._conn.execute(query, (max(1, min(limit, 500)),)).fetchall()]

    def retry_failure(self, failure_id: int) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT * FROM task_failures WHERE id = ? AND resolved_at IS NULL", (failure_id,)).fetchone()
            if not row:
                return False
            self.enqueue(row["monitor_root"], row["path"], row["action"])
            now = time.time()
            self._conn.execute("UPDATE task_failures SET resolved_at = ?, updated_at = ? WHERE id = ?", (now, now, failure_id))
            self._conn.commit()
            return True

    def prune(self, now: Optional[float] = None) -> None:
        now = now or time.time()
        with self._lock:
            self._conn.execute("DELETE FROM task_runs WHERE started_at < ?", (now - 90 * 86400,))
            self._conn.execute("DELETE FROM task_failures WHERE resolved_at IS NOT NULL AND resolved_at < ?", (now - 30 * 86400,))
            self._conn.execute("DELETE FROM cleanup_batches WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < ?", (now,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
                self._conn.close()
            except sqlite3.Error:
                pass

    @staticmethod
    def _job(row: sqlite3.Row) -> PendingJob:
        return PendingJob(
            id=int(row["id"]), monitor_root=row["monitor_root"], path=row["path"],
            action=row["action"], old_path=row["old_path"], attempts=int(row["attempts"]),
            available_at=float(row["available_at"]), payload=json.loads(row["payload"] or "{}"),
        )
