"""Persistent task, failure, and cleanup state for reliable STRM synchronization."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional


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


def classify_failure(error: str, actual_target: str = "") -> dict:
    """Turn a raw sync error into a concise diagnosis and repair hint."""
    raw = str(error or "").strip()
    text = raw.lower()

    if "permission denied" in text or "errno 13" in text or "access is denied" in text:
        return {
            "reason_code": "permission_denied",
            "reason_label": "目标目录没有写入权限",
            "retryable": False,
            "repair_hint": "请给 MoviePilot 运行账号授予目标目录的写入、创建目录和修改文件权限；NAS 还要检查 ACL、UID/GID 以及挂载是否为只读，修复后再重试。",
            "actual_target": actual_target,
        }
    if "read-only file system" in text or "errno 30" in text or "readonly" in text:
        return {
            "reason_code": "read_only_mount",
            "reason_label": "目标挂载是只读的",
            "retryable": False,
            "repair_hint": "检查 NAS、SMB/NFS 挂载状态和挂载参数，重新以读写方式挂载后再重试。",
            "actual_target": actual_target,
        }
    if "no space left" in text or "errno 28" in text or "disk full" in text:
        return {
            "reason_code": "disk_full",
            "reason_label": "目标磁盘空间不足",
            "retryable": False,
            "repair_hint": "清理目标挂载的空间或扩容，确认 inode 没有耗尽后再重试。",
            "actual_target": actual_target,
        }
    if "no such file or directory" in text or "file not found" in text or "errno 2" in text:
        return {
            "reason_code": "path_missing",
            "reason_label": "源文件或目标路径不存在",
            "retryable": False,
            "repair_hint": "确认源文件仍存在、目标挂载已连接，并检查 STRM 规则中的本地目录和输出目录映射。",
            "actual_target": actual_target,
        }
    if any(token in text for token in ("connection timed out", "timed out", "i/o error", "input/output error", "stale file handle", "temporarily unavailable")):
        return {
            "reason_code": "storage_unavailable",
            "reason_label": "NAS 或挂载暂时不可用",
            "retryable": True,
            "repair_hint": "检查 NAS 在线状态、网络连接和挂载日志；连接恢复后可直接重试。",
            "actual_target": actual_target,
        }
    if any(token in text for token in ("template invalid", "invalid template", "invalid_content", "strm 模板")):
        return {
            "reason_code": "invalid_template",
            "reason_label": "STRM 模板或规则无效",
            "retryable": False,
            "repair_hint": "检查规则是否包含 {local_file} 或 {cloud_file}，并确认云盘目录映射有效。",
            "actual_target": actual_target,
        }
    return {
        "reason_code": "unknown",
        "reason_label": "未分类错误",
        "retryable": False,
        "repair_hint": "先查看原始错误并确认源文件、目标挂载和规则配置，修复后再重试。",
        "actual_target": actual_target,
    }


class TaskStore:
    """SQLite store for resumable work. Successful file state stays in SyncStateStore."""

    SCHEMA_VERSION = 4

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
            current = 1
        if current < 2:
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(task_runs)").fetchall()}
            if "skipped" not in columns:
                self._conn.execute("ALTER TABLE task_runs ADD COLUMN skipped INTEGER NOT NULL DEFAULT 0")
            self._conn.execute("UPDATE schema_version SET version = 2")
            current = 2
        if current < 3:
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(task_runs)").fetchall()}
            if "result_counts" not in columns:
                self._conn.execute("ALTER TABLE task_runs ADD COLUMN result_counts TEXT NOT NULL DEFAULT '{}'")
            self._conn.execute("UPDATE schema_version SET version = 3")
            current = 3
        if current < 4:
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(task_failures)").fetchall()}
            if "actual_target" not in columns:
                self._conn.execute("ALTER TABLE task_failures ADD COLUMN actual_target TEXT NOT NULL DEFAULT ''")
            self._conn.execute("UPDATE schema_version SET version = 4")
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

    def retry_job(self, job: PendingJob, error: str, delay: float, diagnosis: Optional[dict] = None) -> None:
        now = time.time()
        attempts = job.attempts + 1
        with self._lock:
            self._conn.execute(
                "UPDATE pending_jobs SET attempts = ?, available_at = ?, updated_at = ? WHERE id = ?",
                (attempts, now + delay, now, job.id),
            )
            self._upsert_failure(job.monitor_root, job.path, job.action, error, attempts, now, diagnosis)
            self._conn.commit()

    def fail_job(self, job: PendingJob, error: str, diagnosis: Optional[dict] = None) -> None:
        now = time.time()
        with self._lock:
            self._upsert_failure(job.monitor_root, job.path, job.action, error, job.attempts + 1, now, diagnosis)
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

    def _upsert_failure(self, root: str, path: str, action: str, error: str, attempts: int, now: float, diagnosis: Optional[dict] = None) -> None:
        actual_target = str((diagnosis or {}).get("actual_target") or "")
        row = self._conn.execute(
            "SELECT id FROM task_failures WHERE monitor_root = ? AND path = ? AND action = ? AND resolved_at IS NULL",
            (root, path, action),
        ).fetchone()
        if row:
            self._conn.execute(
                "UPDATE task_failures SET error = ?, actual_target = ?, attempts = ?, updated_at = ? WHERE id = ?",
                (error[:2000], actual_target, attempts, now, row["id"]),
            )
        else:
            self._conn.execute(
                "INSERT INTO task_failures(monitor_root,path,action,error,actual_target,attempts,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (root, path, action, error[:2000], actual_target, attempts, now, now),
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
        allowed = {key: int(value) for key, value in counts.items() if key in {"queued", "processed", "unchanged", "failed", "deleted", "skipped"}}
        if not allowed:
            return
        columns = ", ".join(f"{key} = {key} + ?" for key in allowed)
        with self._lock:
            self._conn.execute(f"UPDATE task_runs SET {columns} WHERE run_id = ?", (*allowed.values(), run_id))
            self._conn.commit()

    def update_run_result_counts(self, run_id: str, statuses) -> None:
        """Accumulate user-facing per-file result categories for a run."""
        values = statuses.keys() if isinstance(statuses, dict) else statuses or []
        increments = {
            str(key): int(value)
            for key, value in (statuses.items() if isinstance(statuses, dict) else ((key, 1) for key in values))
            if str(key) and int(value) > 0
        }
        if not increments:
            return
        with self._lock:
            row = self._conn.execute(
                "SELECT result_counts FROM task_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if not row:
                return
            try:
                result_counts = json.loads(row["result_counts"] or "{}")
            except (TypeError, ValueError):
                result_counts = {}
            for key, value in increments.items():
                result_counts[key] = int(result_counts.get(key) or 0) + value
            self._conn.execute(
                "UPDATE task_runs SET result_counts = ? WHERE run_id = ?",
                (json.dumps(result_counts, ensure_ascii=False, separators=(",", ":")), run_id),
            )
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
                "SELECT queued, processed, unchanged, failed, deleted, skipped, status FROM task_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if not row or row["status"] != "running":
                return False
            completed = (
                int(row["processed"])
                + int(row["unchanged"])
                + int(row["failed"])
                + int(row["deleted"])
                + int(row["skipped"])
            )
            if completed < int(row["queued"]):
                return False
            final_status = "completed_with_errors" if int(row["failed"]) else "completed"
            self._conn.execute(
                "UPDATE task_runs SET status = ?, finished_at = ? WHERE run_id = ?",
                (final_status, time.time(), run_id),
            )
            self._conn.commit()
            return True

    def create_cleanup_batch(
        self,
        monitor_root: str,
        paths: Iterable[str],
        ttl_seconds: int = 7 * 86400,
        records: Optional[Iterable[Any]] = None,
    ) -> Optional[str]:
        unique_paths = sorted({str(path) for path in paths if path})
        if not unique_paths:
            return None

        if records is None:
            cleanup_items: list[Any] = unique_paths
        else:
            cleanup_items = []
            for record in records:
                source_rel = str(getattr(record, "source_rel", "") or "")
                outputs = sorted({str(output) for output in getattr(record, "outputs", ()) if output})
                if source_rel and outputs:
                    cleanup_items.append(
                        {
                            "monitor_root": monitor_root,
                            "source_rel": source_rel,
                            "outputs": outputs,
                        }
                    )
            if not cleanup_items:
                return None

        batch_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO cleanup_batches(batch_id,monitor_root,status,paths,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                (batch_id, monitor_root, "pending", json.dumps(cleanup_items, ensure_ascii=False), now, now + ttl_seconds),
            )
            self._conn.commit()
        return batch_id

    def claim_cleanup_batch(self, batch_id: str) -> Optional[List[Any]]:
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
        def run_dict(row):
            item = dict(row)
            try:
                parsed_counts = json.loads(item.get("result_counts") or "{}")
                item["result_counts"] = parsed_counts if isinstance(parsed_counts, dict) else {}
            except (TypeError, ValueError):
                item["result_counts"] = {}
            legacy_skipped = int(item["result_counts"].pop("skipped", 0) or 0)
            item["result_counts"]["existing_skipped"] = int(item["result_counts"].get("existing_skipped") or 0) + legacy_skipped
            for key in ("existing_skipped", "copied_non_media", "copied_subtitle", "generated_strm", "failed"):
                item["result_counts"].setdefault(key, 0)
            return item

        return {
            "queued": queued,
            "running": [run_dict(row) for row in running],
            "recent_runs": [run_dict(row) for row in latest],
            "cleanup_batches": [{**dict(row), "path_count": len(json.loads(row["paths"]))} for row in pending_cleanup],
        }

    def failures(self, limit: int = 100, include_resolved: bool = False) -> List[dict]:
        query = "SELECT * FROM task_failures"
        if not include_resolved:
            query += " WHERE resolved_at IS NULL"
        query += " ORDER BY updated_at DESC LIMIT ?"
        with self._lock:
            items = [dict(row) for row in self._conn.execute(query, (max(1, min(limit, 500)),)).fetchall()]
        for item in items:
            item.update(classify_failure(item.get("error", ""), item.get("actual_target", "")))
        return items

    def retry_failure(self, failure_id: int) -> bool:
        return bool(self.retry_failures([failure_id]))

    def retry_failures(self, failure_ids: Iterable[int]) -> List[int]:
        """Requeue open failures and return only IDs accepted by the store."""
        requested = []
        for failure_id in failure_ids or []:
            try:
                value = int(failure_id)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in requested:
                requested.append(value)
        if not requested:
            return []

        retried = []
        with self._lock:
            now = time.time()
            for failure_id in requested:
                row = self._conn.execute(
                    "SELECT * FROM task_failures WHERE id = ? AND resolved_at IS NULL",
                    (failure_id,),
                ).fetchone()
                if not row:
                    continue
                self.enqueue(row["monitor_root"], row["path"], row["action"])
                self._conn.execute(
                    "UPDATE task_failures SET resolved_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, failure_id),
                )
                retried.append(failure_id)
            self._conn.commit()
        return retried

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
