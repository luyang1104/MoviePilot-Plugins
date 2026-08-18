import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.stubs import FakeWatchdogEvent, load_plugin_module

load_plugin_module()

from cloudstrmbutler.monitoring import (
    FileMonitorHandler,
    is_ignored_path,
    is_temporary_path,
    wait_for_stable_file,
)


class MonitoringTests(unittest.TestCase):
    def test_ignored_paths(self):
        self.assertTrue(is_ignored_path(r"C:\media\.hidden\a.mkv"))
        self.assertTrue(is_ignored_path(r"C:\media\@Recycle\a.mkv"))
        self.assertFalse(is_ignored_path(r"C:\media\Show\a.mkv"))

    def test_temporary_paths(self):
        self.assertTrue(is_temporary_path(r"C:\media\movie.mkv.part"))
        self.assertTrue(is_temporary_path(r"C:\media\movie.mkv.crdownload"))
        self.assertTrue(is_temporary_path(r"C:\media\~$notes.docx"))
        self.assertFalse(is_temporary_path(r"C:\media\movie.mkv"))

    def test_handler_translates_events(self):
        class Recorder:
            def __init__(self):
                self.events = []

            def event_handler(self, **kwargs):
                self.events.append(kwargs)

        recorder = Recorder()
        handler = FileMonitorHandler(r"C:\media", recorder)
        handler.on_created(FakeWatchdogEvent(r"C:\media\a.mkv"))
        handler.on_moved(FakeWatchdogEvent(r"C:\media\a.mkv", r"C:\media\b.mkv"))
        handler.on_deleted(FakeWatchdogEvent(r"C:\media\b.mkv"))
        self.assertEqual(
            [(item["action"], item["event_path"]) for item in recorder.events],
            [
                ("created", r"C:\media\a.mkv"),
                ("moved", r"C:\media\b.mkv"),
                ("deleted", r"C:\media\b.mkv"),
            ],
        )

    def test_wait_for_stable_file_returns_true_after_two_stable_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "movie.mkv"
            path.write_bytes(b"abc")
            with patch("cloudstrmbutler.monitoring.time.sleep"):
                self.assertTrue(
                    wait_for_stable_file(
                        str(path),
                        stable_checks=2,
                        stable_interval=0,
                        max_wait=10,
                    )
                )

    def test_wait_for_stable_file_accepts_stable_empty_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "movie.srt"
            path.write_bytes(b"")
            with patch("cloudstrmbutler.monitoring.time.sleep"):
                self.assertTrue(
                    wait_for_stable_file(
                        str(path),
                        stable_checks=2,
                        stable_interval=0,
                        max_wait=10,
                    )
                )

    def test_wait_for_stable_file_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertFalse(
                wait_for_stable_file(
                    str(Path(temp_dir) / "missing.mkv"),
                    stable_checks=2,
                    stable_interval=0,
                    max_wait=0.1,
                )
            )


if __name__ == "__main__":
    unittest.main()
