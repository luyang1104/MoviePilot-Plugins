"""Watchdog adapters and file-event safety checks."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Iterable

from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)

IGNORED_DIR_NAMES = {"extrafanart", "@recycle", "#recycle", "@eadir"}
TEMP_FILE_SUFFIXES = {".part", ".!qb", ".crdownload", ".download", ".tmp", ".aria2"}


class FileMonitorHandler(FileSystemEventHandler):
    """Translate watchdog events into the plugin callback contract."""

    def __init__(self, monpath: str, sync: Any, **kwargs):
        super().__init__(**kwargs)
        self._watch_path = monpath
        self.sync = sync

    def on_created(self, event):
        self.sync.event_handler(
            event=event,
            text="创建",
            mon_path=self._watch_path,
            event_path=event.src_path,
            action="created",
        )

    def on_modified(self, event):
        self.sync.event_handler(
            event=event,
            text="修改",
            mon_path=self._watch_path,
            event_path=event.src_path,
            action="modified",
        )

    def on_moved(self, event):
        self.sync.event_handler(
            event=event,
            text="移动",
            mon_path=self._watch_path,
            event_path=event.dest_path,
            old_event_path=event.src_path,
            action="moved",
        )

    def on_deleted(self, event):
        self.sync.event_handler(
            event=event,
            text="删除",
            mon_path=self._watch_path,
            event_path=event.src_path,
            action="deleted",
        )


def is_ignored_path(event_path: str, ignored_names: Iterable[str] = IGNORED_DIR_NAMES) -> bool:
    path = Path(str(event_path))
    ignored = {str(name).lower() for name in ignored_names}
    for part in path.parts:
        lower_part = part.lower()
        if lower_part in ignored or lower_part.startswith("."):
            return True
    return path.name.lower().startswith(".fuse_hidden")


def is_temporary_path(event_path: str) -> bool:
    name = Path(str(event_path)).name.lower()
    return (
        name.startswith(".fuse_hidden")
        or name.startswith("~$")
        or any(name.endswith(suffix) for suffix in TEMP_FILE_SUFFIXES)
    )


def wait_for_stable_file(
    event_path: str,
    stable_checks: int = 2,
    stable_interval: float = 2.0,
    max_wait: float = 30.0,
) -> bool:
    """Wait until file size and mtime stop changing."""
    source = Path(event_path)
    start = time.monotonic()
    previous = None
    stable_count = 0

    while time.monotonic() - start < max_wait:
        try:
            if not source.exists() or not source.is_file():
                return False
            stat = source.stat()
            current = (stat.st_size, getattr(stat, "st_mtime_ns", stat.st_mtime))
        except OSError:
            return False

        if current == previous:
            stable_count += 1
            if stable_count >= stable_checks:
                return True
        else:
            previous = current
            stable_count = 0
        time.sleep(stable_interval)

    logger.warning("文件在 %s 秒内未稳定，暂不处理：%s", max_wait, event_path)
    return False
