"""Small SQLite-backed index for incremental file synchronization."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .core_paths import path_key


@dataclass(frozen=True)
class SyncRecord:
    monitor_root: str
    source_rel: str
    mtime_ns: int
    size: int
    content_hash: str
    outputs: Tuple[str, ...]
    config_fingerprint: str


class SyncStateStore:
    """Persist source signatures and plugin-generated outputs."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path),
            timeout=30,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_records (
                    monitor_root TEXT NOT NULL,
                    source_rel TEXT NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    outputs TEXT NOT NULL,
                    config_fingerprint TEXT NOT NULL,
                    PRIMARY KEY (monitor_root, source_rel)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sync_records_root ON sync_records(monitor_root)"
            )
            self._conn.commit()

    @staticmethod
    def _normalise_root(root: str) -> str:
        return path_key(root)

    @staticmethod
    def _normalise_rel(relative: str) -> str:
        return str(Path(str(relative))).replace("\\", "/")

    def get(self, monitor_root: str, source_rel: str) -> Optional[SyncRecord]:
        root = self._normalise_root(monitor_root)
        rel = self._normalise_rel(source_rel)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sync_records WHERE monitor_root = ? AND source_rel = ?",
                (root, rel),
            ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def upsert(
        self,
        monitor_root: str,
        source_rel: str,
        mtime_ns: int,
        size: int,
        content_hash: str,
        outputs: Iterable[str],
        config_fingerprint: str,
    ):
        root = self._normalise_root(monitor_root)
        rel = self._normalise_rel(source_rel)
        outputs_json = json.dumps(
            sorted(path_key(item) for item in outputs if item),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sync_records (
                    monitor_root, source_rel, mtime_ns, size, content_hash,
                    outputs, config_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(monitor_root, source_rel) DO UPDATE SET
                    mtime_ns = excluded.mtime_ns,
                    size = excluded.size,
                    content_hash = excluded.content_hash,
                    outputs = excluded.outputs,
                    config_fingerprint = excluded.config_fingerprint
                """,
                (root, rel, int(mtime_ns), int(size), content_hash, outputs_json, config_fingerprint),
            )
            self._conn.commit()

    def delete(self, monitor_root: str, source_rel: str) -> Optional[SyncRecord]:
        root = self._normalise_root(monitor_root)
        rel = self._normalise_rel(source_rel)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sync_records WHERE monitor_root = ? AND source_rel = ?",
                (root, rel),
            ).fetchone()
            if not row:
                return None
            self._conn.execute(
                "DELETE FROM sync_records WHERE monitor_root = ? AND source_rel = ?",
                (root, rel),
            )
            self._conn.commit()
        return self._row_to_record(row)

    def remove_output(self, monitor_root: str, output: str) -> bool:
        """Remove one generated output from every record that owns it."""
        wanted = path_key(output)
        if not wanted:
            return False
        root = self._normalise_root(monitor_root)
        changed = False
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sync_records WHERE monitor_root = ?",
                (root,),
            ).fetchall()
            for row in rows:
                record = self._row_to_record(row)
                outputs = [item for item in record.outputs if path_key(item) != wanted]
                if len(outputs) == len(record.outputs):
                    continue
                changed = True
                if outputs:
                    self._conn.execute(
                        "UPDATE sync_records SET outputs = ? WHERE monitor_root = ? AND source_rel = ?",
                        (json.dumps(outputs, ensure_ascii=False, separators=(",", ":")), root, record.source_rel),
                    )
                else:
                    self._conn.execute(
                        "DELETE FROM sync_records WHERE monitor_root = ? AND source_rel = ?",
                        (root, record.source_rel),
                    )
            if changed:
                self._conn.commit()
        return changed

    def remove_output_for_source(self, monitor_root: str, source_rel: str, output: str) -> bool:
        """Remove one output from one source record without touching shared owners."""
        wanted = path_key(output)
        if not wanted:
            return False
        root = self._normalise_root(monitor_root)
        rel = self._normalise_rel(source_rel)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sync_records WHERE monitor_root = ? AND source_rel = ?",
                (root, rel),
            ).fetchone()
            if not row:
                return False
            record = self._row_to_record(row)
            outputs = [item for item in record.outputs if path_key(item) != wanted]
            if len(outputs) == len(record.outputs):
                return False
            if outputs:
                self._conn.execute(
                    "UPDATE sync_records SET outputs = ? WHERE monitor_root = ? AND source_rel = ?",
                    (json.dumps(outputs, ensure_ascii=False, separators=(",", ":")), root, rel),
                )
            else:
                self._conn.execute(
                    "DELETE FROM sync_records WHERE monitor_root = ? AND source_rel = ?",
                    (root, rel),
                )
            self._conn.commit()
        return True

    def has_output(self, monitor_root: str, output: str) -> bool:
        """Return whether another persisted source still owns an output."""
        wanted = path_key(output)
        if not wanted:
            return False
        root = self._normalise_root(monitor_root)
        with self._lock:
            rows = self._conn.execute(
                "SELECT outputs FROM sync_records WHERE monitor_root = ?",
                (root,),
            ).fetchall()
        return any(
            wanted in {path_key(item) for item in json.loads(row["outputs"] or "[]")}
            for row in rows
        )

    def reap(
        self,
        monitor_root: str,
        seen_relative_paths: Iterable[str],
    ) -> List[SyncRecord]:
        """Delete records no longer present in a completed directory walk."""
        root = self._normalise_root(monitor_root)
        seen = {self._normalise_rel(item) for item in seen_relative_paths}
        stale_records: List[SyncRecord] = []

        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sync_records WHERE monitor_root = ?",
                (root,),
            ).fetchall()
            for row in rows:
                record = self._row_to_record(row)
                if record.source_rel not in seen:
                    stale_records.append(record)
            if stale_records:
                stale_keys = [(record.source_rel,) for record in stale_records]
                self._conn.executemany(
                    "DELETE FROM sync_records WHERE monitor_root = ? AND source_rel = ?",
                    [(root, key[0]) for key in stale_keys],
                )
            self._conn.commit()
        return stale_records

    def records_for_root(self, monitor_root: str) -> List[SyncRecord]:
        root = self._normalise_root(monitor_root)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sync_records WHERE monitor_root = ?",
                (root,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete_records_for_outputs(self, monitor_root: str, outputs: Iterable[str]) -> List[SyncRecord]:
        """Forget only records whose plugin-owned outputs were explicitly confirmed for removal."""
        wanted = {path_key(item) for item in outputs if item}
        if not wanted:
            return []
        root = self._normalise_root(monitor_root)
        deleted: List[SyncRecord] = []
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sync_records WHERE monitor_root = ?", (root,)
            ).fetchall()
            for row in rows:
                record = self._row_to_record(row)
                if any(path_key(output) in wanted for output in record.outputs):
                    deleted.append(record)
            if deleted:
                self._conn.executemany(
                    "DELETE FROM sync_records WHERE monitor_root = ? AND source_rel = ?",
                    [(root, record.source_rel) for record in deleted],
                )
            self._conn.commit()
        return deleted

    def close(self):
        with self._lock:
            try:
                self._conn.commit()
                self._conn.close()
            except sqlite3.Error:
                pass

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> SyncRecord:
        outputs = json.loads(row["outputs"] or "[]")
        return SyncRecord(
            monitor_root=row["monitor_root"],
            source_rel=row["source_rel"],
            mtime_ns=int(row["mtime_ns"]),
            size=int(row["size"]),
            content_hash=row["content_hash"],
            outputs=tuple(outputs),
            config_fingerprint=row["config_fingerprint"],
        )
