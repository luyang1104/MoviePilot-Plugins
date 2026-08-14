import tempfile
import time
import unittest
from pathlib import Path

from tests.stubs import load_plugin_module

load_plugin_module()

from cloudstrmbutler.sync_engine import SyncEngine
from cloudstrmbutler.task_store import TaskStore


class SyncEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp_dir.name) / "tasks.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_engine_processes_persisted_job(self):
        seen = []
        engine = SyncEngine(self.store, lambda job: seen.append(job.path) or {"status": "processed"}, workers=1)
        engine.start()
        engine.enqueue("/media", "/media/movie.mkv")
        deadline = time.time() + 2
        while not seen and time.time() < deadline:
            time.sleep(0.02)
        engine.stop()
        self.assertEqual(seen, ["/media/movie.mkv"])
        self.assertEqual(self.store.status()["queued"], 0)

    def test_snapshot_counts_only_active_workers_as_inflight(self):
        started = []
        release = __import__("threading").Event()

        def handler(job):
            started.append(job.path)
            release.wait(2)
            return {"status": "processed"}

        engine = SyncEngine(self.store, handler, workers=2, max_queue=100)
        engine.start()
        for index in range(8):
            engine.enqueue("/media", f"/media/{index}.mkv")

        deadline = time.time() + 2
        while len(started) < 2 and time.time() < deadline:
            time.sleep(0.02)

        snapshot = engine.snapshot()
        release.set()
        engine.stop()

        self.assertEqual(snapshot["inflight"], 2)
        self.assertEqual(snapshot["memory_queued"], 6)
        self.assertEqual(snapshot["scheduled"], 8)


if __name__ == "__main__":
    unittest.main()
