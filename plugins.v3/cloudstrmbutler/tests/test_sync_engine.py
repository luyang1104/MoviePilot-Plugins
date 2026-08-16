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

    def test_event_during_processing_is_run_as_a_follow_up_generation(self):
        started = __import__("threading").Event()
        release = __import__("threading").Event()
        seen = []

        def handler(job):
            seen.append(job.payload)
            if len(seen) == 1:
                started.set()
                release.wait(2)
            return {"status": "processed"}

        engine = SyncEngine(self.store, handler, workers=1)
        engine.start()
        engine.enqueue("/media", "/media/movie.mkv")
        self.assertTrue(started.wait(1))
        self.assertTrue(
            engine.enqueue(
                "/media",
                "/media/movie.mkv",
                payload={"run_id": "scan-1"},
            )
        )
        release.set()

        deadline = time.time() + 2
        while len(seen) < 2 and time.time() < deadline:
            time.sleep(0.02)
        engine.stop()

        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[1]["run_id"], "scan-1")
        self.assertEqual(self.store.status()["queued"], 0)

    def test_stop_drains_a_follow_up_generation_before_closing_workers(self):
        started = __import__("threading").Event()
        release = __import__("threading").Event()
        seen = []

        def handler(job):
            seen.append(job.payload)
            if len(seen) == 1:
                started.set()
                release.wait(2)
            return {"status": "processed"}

        engine = SyncEngine(self.store, handler, workers=1)
        engine.start()
        engine.enqueue("/media", "/media/movie.mkv")
        self.assertTrue(started.wait(1))
        engine.enqueue("/media", "/media/movie.mkv", payload={"run_id": "scan-1"})
        release.set()

        self.assertTrue(engine.stop(timeout=2))
        self.assertEqual(len(seen), 2)
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

    def test_stop_reports_false_until_running_worker_has_finished(self):
        started = __import__("threading").Event()
        release = __import__("threading").Event()

        def handler(job):
            started.set()
            release.wait(2)
            return {"status": "processed"}

        engine = SyncEngine(self.store, handler, workers=1)
        engine.start()
        engine.enqueue("/media", "/media/slow.mkv")

        self.assertTrue(started.wait(1))
        self.assertFalse(engine.stop(timeout=0.01))
        self.assertTrue(engine._threads)

        release.set()
        self.assertTrue(engine.stop(timeout=2))
        self.assertFalse(engine._threads)

    def test_invalid_result_is_failed_and_kept_in_failures(self):
        completed = []
        engine = SyncEngine(
            self.store,
            lambda job: {
                "status": "invalid_target",
                "reason": "目标路径无效",
                "actual_target": "/library/movie.strm",
                "diagnosis": {"reason_code": "invalid_target", "actual_target": "/library/movie.strm"},
            },
            workers=1,
            completion=lambda job, result: completed.append(result),
        )
        engine.start()
        engine.enqueue("/media", "/media/movie.mkv")

        deadline = time.time() + 2
        while not completed and time.time() < deadline:
            time.sleep(0.02)
        engine.stop()

        self.assertEqual(completed[0]["status"], "failed")
        self.assertEqual(completed[0]["reason"], "目标路径无效")
        self.assertEqual(completed[0]["actual_target"], "/library/movie.strm")
        self.assertEqual(len(self.store.failures()), 1)
        self.assertEqual(self.store.failures()[0]["actual_target"], "/library/movie.strm")
        self.assertEqual(self.store.status()["queued"], 0)

    def test_cancelled_generation_keeps_a_later_event_for_the_worker(self):
        import threading

        started = threading.Event()
        release = threading.Event()
        seen = []

        def handler(job):
            seen.append(job.payload)
            if len(seen) == 1:
                started.set()
                release.wait(2)
            return {"status": "processed"}

        engine = SyncEngine(self.store, handler, workers=1)
        engine.start()
        engine.enqueue("/media", "/media/movie.mkv", payload={"run_id": "scan-1"})
        self.assertTrue(started.wait(1))
        engine.enqueue("/media", "/media/movie.mkv", payload={"run_id": "watcher-event"})

        self.assertEqual(self.store.cancel_run_jobs("scan-1"), 1)
        release.set()
        deadline = time.time() + 2
        while len(seen) < 2 and time.time() < deadline:
            time.sleep(0.02)
        engine.stop()

        self.assertEqual([item["run_id"] for item in seen], ["scan-1", "watcher-event"])


if __name__ == "__main__":
    unittest.main()
