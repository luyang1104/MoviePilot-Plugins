import tempfile
import unittest
from pathlib import Path

from tests.stubs import load_plugin_module

load_plugin_module()

from cloudstrmbutler.task_store import TaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp_dir.name) / "tasks.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_enqueue_deduplicates_and_claims_job(self):
        self.assertTrue(self.store.enqueue("/media", "/media/movie.mkv", "sync"))
        self.assertFalse(self.store.enqueue("/media", "/media/movie.mkv", "sync"))
        jobs = self.store.claim_ready()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].path, "/media/movie.mkv")

    def test_failure_can_be_retried(self):
        self.store.enqueue("/media", "/media/movie.mkv", "sync")
        job = self.store.claim_ready()[0]
        self.store.fail_job(job, "template invalid")
        failure = self.store.failures()[0]
        self.assertTrue(self.store.retry_failure(failure["id"]))
        self.assertEqual(len(self.store.claim_ready()), 1)

    def test_cleanup_batch_is_single_use(self):
        batch_id = self.store.create_cleanup_batch("/media", ["/out/a.strm", "/out/a.strm"])
        self.assertEqual(self.store.claim_cleanup_batch(batch_id), ["/out/a.strm"])
        self.assertIsNone(self.store.claim_cleanup_batch(batch_id))

    def test_run_summary_is_exposed(self):
        run_id = self.store.start_run("scan", "/media")
        self.store.update_run(run_id, queued=2, processed=1, unchanged=1)
        self.store.finish_run(run_id)
        run = self.store.status()["recent_runs"][0]
        self.assertEqual(run["queued"], 2)
        self.assertEqual(run["processed"], 1)

    def test_settled_run_counts_skipped_and_deleted_results(self):
        run_id = self.store.start_run("command")
        self.store.update_run(run_id, queued=2, skipped=1, deleted=1)

        self.assertTrue(self.store.finish_run_if_settled(run_id))
        self.assertEqual(self.store.status()["recent_runs"][0]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
