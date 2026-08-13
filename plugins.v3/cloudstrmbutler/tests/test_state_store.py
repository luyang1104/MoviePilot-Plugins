import tempfile
import unittest
from pathlib import Path

from tests.stubs import load_plugin_module

load_plugin_module()

from cloudstrmbutler.state_store import SyncStateStore


class SyncStateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SyncStateStore(Path(self.temp_dir.name) / "state.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_upsert_and_get(self):
        self.store.upsert(
            monitor_root=r"C:\media",
            source_rel=r"Series\Show\movie.mkv",
            mtime_ns=123,
            size=456,
            content_hash="abc",
            outputs=[r"C:\out\Series\Show\movie.strm"],
            config_fingerprint="finger",
        )
        record = self.store.get(r"C:\media", "Series/Show/movie.mkv")
        self.assertIsNotNone(record)
        self.assertEqual(record.mtime_ns, 123)
        self.assertEqual(record.outputs[0], r"C:\out\Series\Show\movie.strm".lower())

    def test_reap_deletes_unseen_sources(self):
        self.store.upsert(
            r"C:\media", "a.mkv", 1, 1, "", [r"C:\out\a.strm"], "finger"
        )
        self.store.upsert(
            r"C:\media", "b.mkv", 1, 1, "", [r"C:\out\b.strm"], "finger"
        )
        stale = self.store.reap(r"C:\media", ["b.mkv"])
        self.assertEqual([item.source_rel for item in stale], ["a.mkv"])
        self.assertIsNone(self.store.get(r"C:\media", "a.mkv"))
        self.assertIsNotNone(self.store.get(r"C:\media", "b.mkv"))

    def test_delete_returns_record(self):
        self.store.upsert(
            r"C:\media", "a.mkv", 1, 1, "hash", [r"C:\out\a.strm"], "finger"
        )
        deleted = self.store.delete(r"C:\media", "a.mkv")
        self.assertIsNotNone(deleted)
        self.assertEqual(deleted.content_hash, "hash")
        self.assertIsNone(self.store.get(r"C:\media", "a.mkv"))


if __name__ == "__main__":
    unittest.main()
