"""Watchdog adapters and file-event safety checks."""

from __future__ import annotations

import os
import logging
import time
from pathlib import Path
from typing import Any, Iterable

from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)


IGNORED_DIR_NAMES = {"extrafanart", "@recycle", "#recycle", "@eadir"}


class FileMonitorHandler(FileSystemEventHandler):
    """Translate watchdog events into the plugin callback contract."""

    def __init__(self, monpath: str, sync: Any, **kwargs):
        super().__init__(**kwargs)
        self._watch_path = monpath
        self.sync = sync

    def on_created(self, event):
        self.sync.event_handler(
            event=event, text="创建", mon_path=self._watch_path,
            event_path=event.src_path, action="created",
        )

    def on_modified(self, event):
        self.sync.event_handler(
            event=event, text="修改", mon_path=self._watch_path,
            event_path=event.src_path, action="modified",
        )

    def on_moved(self, event):
        self.sync.event_handler(
            event=event, text="移动", mon_path=self._watch_path,
            event_path=event.dest_path, old_event_path=event.src_path,
            action="moved",
        )

    def on_deleted(self, event):
        self.sync.event_handler(
            event=event, text="删除", mon_path=self._watch_path,
            event_path=event.src_path, action="deleted",
        )


def is_ignored_path(event_path: str, ignored_names: Iterable[str] = IGNORED_DIR_NAMES) -> bool:
    path = Path(str(event_path))
    ignored = {str(name).lower() for name in ignored_names}
    for part in path.parts:
        lower_part = part.lower()
        if lower_part in ignored or lower_part.startswith("."):
            return True
    return path.name.lower().startswith(".fuse_hidden")


def wait_for_stable_file(
    event_path: str,
    stable_checks: int = 2,
    stable_interval: float = 0.5,
    attempts: int = 10,
) -> bool:
    """Wait until size and mtime stop changing before processing a file."""
    previous = None
    stable_count = 0
    for _ in range(attempts):
        try:
            stat = os.stat(event_path)
        except OSError:
            return False
        current = (stat.st_size, getattr(stat, "st_mtime_ns", stat.st_mtime))
        if current == previous:
            stable_count += 1
            if stable_count >= stable_checks:
                return True
        else:
            previous = current
            stable_count = 0
        time.sleep(stable_interval)
    logger.warning("file did not become stable before the retry limit: %s", event_path)
    return Path(event_path).is_file()
