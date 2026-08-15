import tempfile
import unittest
from pathlib import Path

from tests.stubs import load_plugin_module

load_plugin_module()

from cloudstrmbutler.task_store import TaskStore, classify_failure


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

    def test_failures_expose_permission_diagnosis_and_repair_hint(self):
        self.store.enqueue("/media", "/media/movie.ass", "sync")
        job = self.store.claim_ready()[0]
        self.store.fail_job(job, "[Errno 13] Permission denied: '/library/movie.ass'")

        failure = self.store.failures()[0]

        self.assertEqual(failure["reason_code"], "permission_denied")
        self.assertFalse(failure["retryable"])
        self.assertIn("写入", failure["repair_hint"])

    def test_failures_keep_actual_strm_output_target(self):
        self.store.enqueue("/media", "/media/movie.mkv", "sync")
        job = self.store.claim_ready()[0]
        self.store.fail_job(job, "[Errno 13] Permission denied", {"actual_target": "/library/movie.strm"})

        failure = self.store.failures()[0]

        self.assertEqual(failure["actual_target"], "/library/movie.strm")

    def test_batch_retry_deduplicates_ids_and_ignores_resolved_failures(self):
        self.store.enqueue("/media", "/media/one.mkv", "sync")
        self.store.enqueue("/media", "/media/two.mkv", "sync")
        jobs = self.store.claim_ready()
        self.store.fail_job(jobs[0], "template invalid")
        self.store.fail_job(jobs[1], "template invalid")
        failures = self.store.failures()
        first_id = failures[0]["id"]
        second_id = failures[1]["id"]

        self.assertEqual(self.store.retry_failures([first_id, first_id, second_id, "invalid", 999]), [first_id, second_id])
        self.assertEqual(self.store.retry_failures([first_id, second_id]), [])
        self.assertEqual({job.path for job in self.store.claim_ready()}, {"/media/one.mkv", "/media/two.mkv"})

    def test_failure_classifier_marks_transient_storage_errors_retryable(self):
        diagnosis = classify_failure("[Errno 110] Connection timed out")

        self.assertEqual(diagnosis["reason_code"], "storage_unavailable")
        self.assertTrue(diagnosis["retryable"])

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

    def test_run_result_categories_are_exposed(self):
        run_id = self.store.start_run("command", "/media")
        self.store.update_run_result_counts(run_id, ["generated_strm", "copied_subtitle", "existing_skipped"])
        self.store.finish_run(run_id)

        counts = self.store.status()["recent_runs"][0]["result_counts"]

        self.assertEqual(counts["generated_strm"], 1)
        self.assertEqual(counts["copied_subtitle"], 1)
        self.assertEqual(counts["existing_skipped"], 1)
        self.assertEqual(counts["failed"], 0)

    def test_settled_run_counts_skipped_and_deleted_results(self):
        run_id = self.store.start_run("command")
        self.store.update_run(run_id, queued=2, skipped=1, deleted=1)

        self.assertTrue(self.store.finish_run_if_settled(run_id))
        self.assertEqual(self.store.status()["recent_runs"][0]["status"], "completed")

    def test_settled_run_with_failures_is_marked_completed_with_errors(self):
        run_id = self.store.start_run("scan")
        self.store.update_run(run_id, queued=2, processed=1, failed=1)

        self.assertTrue(self.store.finish_run_if_settled(run_id))
        self.assertEqual(self.store.status()["recent_runs"][0]["status"], "completed_with_errors")


if __name__ == "__main__":
    unittest.main()
