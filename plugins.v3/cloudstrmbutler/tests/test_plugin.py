import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.stubs import FakeEvent, load_plugin_module

plugin_module = load_plugin_module()
CloudStrmButler = plugin_module.CloudStrmButler


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp_dirs = []
        self.plugins = []

    def tearDown(self):
        for plugin in reversed(self.plugins):
            plugin.stop_service()
        for directory in reversed(self.temp_dirs):
            shutil.rmtree(directory, ignore_errors=True)

    def new_temp(self) -> Path:
        directory = tempfile.mkdtemp()
        self.temp_dirs.append(directory)
        return Path(directory)

    def make_plugin(self, data_root: Path):
        plugin = CloudStrmButler()
        plugin.get_data_path = lambda: data_root
        self.plugins.append(plugin)
        return plugin

    def make_rule_paths(self, base: Path):
        source = base / "media"
        target = base / "library"
        cloud = base / "cloud"
        source.mkdir(parents=True, exist_ok=True)
        return source, target, cloud

    @staticmethod
    def wait_until(predicate, timeout=2):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return bool(predicate())

    def test_disabled_init_parses_rules_without_starting_services(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")

        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )

        self.assertEqual(len(plugin._monitor_rules), 1)
        self.assertEqual(plugin._strm_dir_conf[str(source)], str(target))
        self.assertIsNone(plugin._scheduler)
        self.assertEqual(plugin._observer, [])
        self.assertIsNotNone(plugin._state_store)

    def test_moviepilot_v3_abstract_interfaces_are_implemented(self):
        plugin = self.make_plugin(self.new_temp() / "data")

        self.assertEqual(plugin.get_service(), [])
        self.assertEqual(
            [item["path"] for item in plugin.get_api()],
            [
                "/sync_status",
                "/sync_failures",
                "/sync_retry_failure",
                "/sync_retry_failures",
                "/sync_confirm_cleanup",
                "/sync_full_scan",
            ],
        )

    def test_status_api_paths_use_moviepilot_plugin_id_case(self):
        page_source = (Path(__file__).resolve().parent.parent / "src" / "Page.vue").read_text(encoding="utf-8")

        self.assertIn("plugin/CloudStrmButler/sync_status", page_source)
        self.assertIn("plugin/CloudStrmButler/sync_failures", page_source)
        self.assertNotIn("plugin/cloudstrmbutler/", page_source)

    def test_batch_failure_retry_api_requeues_selected_failures(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin({
            "enabled": True,
            "reliable_engine": True,
            "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
        })

        plugin._task_store.enqueue(str(source), str(source / "one.mkv"), "sync")
        job = plugin._task_store.claim_ready()[0]
        plugin._task_store.fail_job(job, "[Errno 13] Permission denied")
        failure_id = plugin._task_store.failures()[0]["id"]

        with patch.object(plugin._sync_engine, "pump") as pump:
            response = plugin.sync_retry_failures_api({"failure_ids": [failure_id, failure_id]})

        self.assertEqual(response["code"], 0)
        self.assertEqual(response["data"]["retried"], 1)
        pump.assert_called_once()
        self.assertEqual(len(plugin._task_store.claim_ready()), 1)

    def test_get_form_prefers_persisted_configuration_over_stale_instance_state(self):
        plugin = self.make_plugin(self.new_temp() / "data")
        plugin.init_plugin({"enabled": False, "monitor": False})
        plugin.get_config = lambda: {
            "enabled": True,
            "monitor": True,
            "interval": 25,
            "rule_0_local": "/source",
            "rule_0_strm": "/strm",
            "rule_0_cloud": "/cloud",
            "rule_0_format": "http://host/{cloud_file}",
        }

        _, model = plugin.get_form()

        self.assertTrue(model["enabled"])
        self.assertTrue(model["monitor"])
        self.assertEqual(model["interval"], 25)
        self.assertEqual(model["rule_0_local"], "/source")
        self.assertEqual(model["rule_0_strm"], "/strm")

    def test_legacy_nomonitor_rule_stays_disabled_in_vue_model(self):
        plugin = self.make_plugin(self.new_temp() / "data")
        rules = plugin._parse_structured_rules(
            {"monitor_confs": r"C:\media#C:\out#D:\cloud#{cloud_file}$nomonitor"}
        )

        self.assertEqual(len(rules), 1)
        self.assertFalse(rules[0]["monitor"])

    def test_structured_payload_round_trips_after_plugin_reload(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        payload = {
            "enabled": "false",
            "monitor": "false",
            "reliable_engine": "false",
            "interval": "15",
            "scan_interval": "30",
            "cleanup_mode": "confirm",
            "rule_0_category": "movie,4K",
            "rule_0_local": str(source),
            "rule_0_strm": str(target),
            "rule_0_cloud": str(cloud),
            "rule_0_format": "http://host/{cloud_file}",
            "rule_0_monitor": "false",
            "rule_0_delete": False,
            "rule_1_delete": True,
        }

        plugin.init_plugin(payload)
        stored = dict(plugin.config)
        reloaded = self.make_plugin(base / "data-reloaded")
        reloaded.init_plugin(stored)

        self.assertFalse(reloaded._enabled)
        self.assertFalse(reloaded._monitor)
        self.assertFalse(reloaded._reliable_engine)
        self.assertEqual(reloaded._interval, 15)
        self.assertEqual(reloaded._scan_interval, 30)
        self.assertEqual(len(reloaded._monitor_rules), 1)
        self.assertEqual(reloaded._monitor_rules[0].local_dir, str(source))
        self.assertFalse(reloaded._monitor_rules[0].should_monitor(True))
        self.assertTrue(stored["rule_1_delete"])

    def test_deleted_structured_slots_do_not_fall_back_to_legacy_rules(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")

        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
                "rule_0_delete": True,
            }
        )

        self.assertEqual(plugin._monitor_rules, [])

    def test_empty_structured_slots_do_not_fall_back_to_legacy_rules(self):
        plugin = self.make_plugin(self.new_temp() / "data")

        rules = plugin._parse_structured_rules(
            {
                "config_version": 2,
                "rule_0_delete": False,
                "monitor_confs": r"C:\legacy#C:\out#D:\cloud#{cloud_file}",
            }
        )

        self.assertEqual(rules, [])

    def test_runtime_reset_does_not_reuse_previous_media_servers(self):
        plugin = self.make_plugin(self.new_temp() / "data")
        plugin._mediaservers = ["stale-server"]

        plugin.init_plugin({"enabled": False})

        self.assertEqual(plugin._mediaservers, [])

    def test_one_time_scan_does_not_reenable_disabled_rule(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")

        plugin.init_plugin(
            {
                "enabled": False,
                "onlyonce": True,
                "rule_0_local": str(source),
                "rule_0_strm": str(target),
                "rule_0_cloud": str(cloud),
                "rule_0_format": "http://host/{cloud_file}",
                "rule_0_monitor": False,
            }
        )

        self.assertFalse(plugin.config["rule_0_monitor"])

    def test_enabled_init_starts_scheduler_and_observer(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")

        plugin.init_plugin(
            {
                "enabled": True,
                "monitor": True,
                "scan_interval": 5,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )

        self.assertIsNotNone(plugin._scheduler)
        self.assertTrue(plugin._scheduler.running)
        scan_jobs = [
            (args, kwargs)
            for args, kwargs in plugin._scheduler.jobs
            if kwargs.get("name") == "云盘Strm小管家定时全量扫描"
        ]
        self.assertEqual(len(scan_jobs), 1)
        self.assertEqual(scan_jobs[0][1]["minutes"], 5)
        self.assertEqual(len(plugin._observer), 1)
        self.assertTrue(plugin._observer[0].running)
        self.assertEqual(len(plugin._observer[0].handlers), 1)

    def test_media_file_is_current_after_first_write(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")

        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )

        series_dir = source / "Series"
        series_dir.mkdir()
        media_file = series_dir / "movie.mkv"
        sidecar = series_dir / "movie.nfo"
        media_file.write_bytes(b"movie bytes")
        sidecar.write_text("sidecar", encoding="utf-8")

        first = plugin._CloudStrmButler__handle_file(
            event_path=str(media_file), mon_path=str(source)
        )
        self.assertEqual(first["status"], "processed")
        self.assertIn(str(target / "Series" / "movie.strm"), first["outputs"])
        self.assertIn(str(target / "Series" / "movie.nfo"), first["outputs"])

        with patch.object(
            plugin, "_CloudStrmButler__create_strm_file"
        ) as create_mock:
            second = plugin._CloudStrmButler__handle_file(
                event_path=str(media_file), mon_path=str(source)
            )
        self.assertEqual(second["status"], "unchanged")
        create_mock.assert_not_called()
        self.assertTrue((target / "Series" / "movie.strm").is_file())

    def test_media_processing_persists_independent_sidecar_record(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "copy_subtitles": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        sidecar = source / "movie.srt"
        media_file.write_bytes(b"movie")
        sidecar.write_text("subtitle", encoding="utf-8")

        plugin._CloudStrmButler__handle_file(str(media_file), str(source))

        sidecar_record = plugin._state_store.get(str(source), "movie.srt")
        self.assertIsNotNone(sidecar_record)
        self.assertEqual(sidecar_record.outputs, (str(target / "movie.srt").lower(),))

    def test_deleting_sidecar_removes_shared_output_but_keeps_strm(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "copy_subtitles": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        sidecar = source / "movie.srt"
        media_file.write_bytes(b"movie")
        sidecar.write_text("subtitle", encoding="utf-8")
        plugin._CloudStrmButler__handle_file(str(media_file), str(source))
        sidecar.unlink()

        plugin._CloudStrmButler__handle_deleted_file(str(sidecar), str(source))

        self.assertFalse((target / "movie.srt").exists())
        self.assertTrue((target / "movie.strm").exists())
        media_record = plugin._state_store.get(str(source), "movie.mkv")
        self.assertNotIn(str(target / "movie.srt").lower(), media_record.outputs)

    def test_confirm_cleanup_keeps_output_owned_by_existing_sidecar(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "copy_subtitles": True,
                "cleanup_mode": "confirm",
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        sidecar = source / "movie.srt"
        media_file.write_bytes(b"movie")
        sidecar.write_text("subtitle", encoding="utf-8")
        plugin._CloudStrmButler__handle_file(str(media_file), str(source))

        media_file.unlink()
        plugin._reconcile_missing_records(str(source), {"movie.srt"})
        batch_id = plugin._task_store.status()["cleanup_batches"][0]["batch_id"]

        result = plugin.sync_confirm_cleanup_api({"batch_id": batch_id})

        self.assertEqual(result["code"], 0)
        self.assertFalse((target / "movie.strm").exists())
        self.assertTrue((target / "movie.srt").exists())
        self.assertIsNotNone(plugin._state_store.get(str(source), "movie.srt"))

    def test_deleting_media_keeps_sidecar_while_sidecar_source_exists(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "copy_subtitles": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        sidecar = source / "movie.srt"
        media_file.write_bytes(b"movie")
        sidecar.write_text("subtitle", encoding="utf-8")
        plugin._CloudStrmButler__handle_file(str(media_file), str(source))

        media_file.unlink()
        plugin._CloudStrmButler__handle_deleted_file(str(media_file), str(source))

        self.assertFalse((target / "movie.strm").exists())
        self.assertTrue((target / "movie.srt").is_file())
        self.assertIsNotNone(plugin._state_store.get(str(source), "movie.srt"))

    def test_delete_removes_recorded_outputs(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")

        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        media_file.write_bytes(b"movie bytes")
        plugin._CloudStrmButler__handle_file(str(media_file), str(source))
        self.assertTrue((target / "movie.strm").is_file())

        plugin._CloudStrmButler__handle_deleted_file(
            str(media_file), str(source)
        )
        self.assertFalse((target / "movie.strm").exists())
        self.assertIsNone(
            plugin._state_store.get(str(source), str(media_file.relative_to(source)))
        )

    def test_sidecar_timeout_is_reported_as_retryable_failure(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")

        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        sidecar = source / "movie.nfo"
        media_file.write_bytes(b"movie bytes")
        sidecar.write_text("sidecar", encoding="utf-8")

        with patch("shutil.copy2", side_effect=OSError(110, "Connection timed out")):
            result = plugin._CloudStrmButler__handle_file(str(media_file), str(source))

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["retryable"])
        self.assertIn("Connection timed out", result["reason"])

    def test_sidecar_atomic_copy_failure_keeps_previous_target_and_cleans_temp(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        sidecar = source / "movie.nfo"
        sidecar.write_text("new", encoding="utf-8")
        destination = target / "movie.nfo"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("old", encoding="utf-8")

        with patch("os.replace", side_effect=OSError(110, "Connection timed out")):
            result = plugin._CloudStrmButler__handle_file(str(sidecar), str(source))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(destination.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(target.glob(".movie.nfo.*.tmp")), [])

    def test_disabling_sidecar_copy_removes_old_output(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        sidecar = source / "movie.nfo"
        sidecar.write_text("nfo", encoding="utf-8")
        plugin._CloudStrmButler__handle_file(str(sidecar), str(source))
        self.assertTrue((target / "movie.nfo").is_file())

        plugin._copy_files = False
        plugin._CloudStrmButler__handle_file(str(sidecar), str(source))

        self.assertFalse((target / "movie.nfo").exists())
        self.assertIsNone(plugin._state_store.get(str(source), "movie.nfo"))

    def test_strm_write_timeout_is_reported_as_retryable_failure(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")

        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        media_file.write_bytes(b"movie bytes")

        with patch("os.replace", side_effect=OSError(110, "Connection timed out")):
            result = plugin._CloudStrmButler__handle_file(str(media_file), str(source))

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["retryable"])
        self.assertIn("Connection timed out", result["reason"])

    def test_remote_command_posts_one_aggregated_result_and_records_run(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        success_file = source / "success.mkv"
        failed_file = source / "failed.mkv"
        success_file.write_bytes(b"success")
        failed_file.write_bytes(b"failed")

        def handle_file(event_path, mon_path):
            if Path(event_path).name == "failed.mkv":
                return {"status": "failed", "reason": "template invalid"}
            return {"status": "processed"}

        with patch.object(plugin, "_CloudStrmButler__handle_file", side_effect=handle_file):
            plugin.remote_sync_one(
                FakeEvent(
                    {
                        "action": "strm_one",
                        "arg_str": str(source),
                        "user": "user-1",
                        "channel": "channel-1",
                    }
                )
            )
            self.assertTrue(self.wait_until(lambda: len(plugin.messages) == 1))

        self.assertTrue(self.wait_until(lambda: len(plugin.messages) == 1))

        self.assertEqual(len(plugin.messages), 1)
        message = plugin.messages[0]
        self.assertEqual(message["userid"], "user-1")
        self.assertIn("总数 2", message["title"])
        self.assertIn("成功 1", message["title"])
        self.assertIn("失败 1", message["title"])
        self.assertIn("template invalid", message["title"])

        run = plugin.sync_status_api()["data"]["recent_runs"][0]
        self.assertEqual(run["kind"], "command")
        self.assertEqual(run["queued"], 2)
        self.assertEqual(run["processed"], 1)
        self.assertEqual(run["failed"], 1)
        self.assertEqual(run["status"], "completed_with_errors")

    def test_manual_command_progress_exposes_current_file_and_stalled_state(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        media_file.write_bytes(b"movie")
        started = threading.Event()
        release = threading.Event()

        def handle_file(event_path, mon_path):
            started.set()
            release.wait(2)
            return {"status": "processed", "result_statuses": ["generated_strm"]}

        with patch.object(plugin, "_CloudStrmButler__handle_file", side_effect=handle_file):
            plugin.remote_sync_one(
                FakeEvent(
                    {
                        "action": "strm_one",
                        "arg_str": str(source),
                        "user": "user-1",
                        "channel": "channel-1",
                    }
                )
            )
            self.assertTrue(started.wait(1))
            progress = plugin.sync_status_api()["data"]["command_progress"]
            self.assertTrue(progress["running"])
            self.assertEqual(progress["processed"], 0)
            self.assertEqual(progress["total"], 1)
            self.assertEqual(progress["current_path"], str(media_file))

            with plugin._command_progress_lock:
                plugin._command_progress["last_progress_at"] = time.time() - plugin._command_stall_seconds - 1
            stalled = plugin.sync_status_api()["data"]["command_progress"]
            self.assertTrue(stalled["stalled"])
            self.assertGreaterEqual(stalled["stalled_seconds"], plugin._command_stall_seconds)
            release.set()

        self.assertTrue(self.wait_until(lambda: not plugin.sync_status_api()["data"]["command_progress"]["running"]))
        progress = plugin.sync_status_api()["data"]["command_progress"]
        self.assertFalse(progress["stalled"])
        self.assertEqual(progress["processed"], 1)

    def test_manual_command_persists_file_result_categories(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "copy_subtitles": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        media_file.write_bytes(b"movie")
        (source / "movie.nfo").write_text("nfo", encoding="utf-8")
        (source / "movie.srt").write_text("subtitle", encoding="utf-8")

        plugin.remote_sync_one(
            FakeEvent(
                {
                    "action": "strm_one",
                    "arg_str": str(source),
                    "user": "user-1",
                    "channel": "channel-1",
                }
            )
        )

        self.assertTrue(self.wait_until(lambda: not plugin.sync_status_api()["data"]["command_progress"]["running"]))
        run = plugin.sync_status_api()["data"]["recent_runs"][0]
        counts = run["result_counts"]
        self.assertEqual(counts["generated_strm"], 1)
        self.assertEqual(counts["copied_non_media"], 1)
        self.assertEqual(counts["copied_subtitle"], 1)
        self.assertEqual(counts["failed"], 0)

    def test_stop_service_does_not_close_stores_while_manual_command_is_running(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin._command_shutdown_timeout = 0.05
        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        media_file.write_bytes(b"movie")
        started = threading.Event()
        release = threading.Event()

        def handle_file(event_path, mon_path):
            started.set()
            release.wait(2)
            return {"status": "processed", "result_statuses": ["generated_strm"]}

        with patch.object(plugin, "_CloudStrmButler__handle_file", side_effect=handle_file):
            plugin.remote_sync_one(FakeEvent({"action": "strm_one", "arg_str": str(source)}))
            self.assertTrue(started.wait(1))
            self.assertFalse(plugin.stop_service())
            self.assertIsNotNone(plugin._task_store)
            self.assertIsNotNone(plugin._state_store)
            release.set()

        self.assertTrue(self.wait_until(lambda: not plugin.sync_status_api()["data"]["command_progress"]["running"]))
        self.assertTrue(plugin.stop_service())
        self.assertIsNone(plugin._task_store)
        self.assertIsNone(plugin._state_store)

    def test_stop_service_does_not_close_stores_while_full_scan_is_running(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin._command_shutdown_timeout = 0.05
        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        media_file.write_bytes(b"movie")
        started = threading.Event()
        release = threading.Event()

        def handle_file(event_path, mon_path):
            started.set()
            release.wait(2)
            return {"status": "processed", "result_statuses": ["generated_strm"]}

        with patch.object(plugin, "_CloudStrmButler__handle_file", side_effect=handle_file):
            self.assertEqual(plugin.sync_full_scan_api({})["code"], 0)
            self.assertTrue(started.wait(1))
            self.assertFalse(plugin.stop_service())
            self.assertIsNotNone(plugin._task_store)
            self.assertIsNotNone(plugin._state_store)
            release.set()

        self.assertTrue(self.wait_until(lambda: not plugin.sync_status_api()["data"]["scan_running"]))
        self.assertTrue(plugin.stop_service())
        self.assertIsNone(plugin._task_store)
        self.assertIsNone(plugin._state_store)

    def test_reliable_full_scan_keeps_state_open_until_queue_job_finishes(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin._command_shutdown_timeout = 0.05
        plugin.init_plugin(
            {
                "enabled": True,
                "monitor": False,
                "reliable_engine": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        media_file.write_bytes(b"movie")
        started = threading.Event()
        release = threading.Event()

        def handle_file(event_path, mon_path, wait_stable=False):
            started.set()
            release.wait(2)
            return {"status": "processed", "result_statuses": ["generated_strm"]}

        with patch.object(plugin, "_CloudStrmButler__handle_file", side_effect=handle_file):
            self.assertEqual(plugin.sync_full_scan_api({})["code"], 0)
            self.assertTrue(started.wait(1))
            self.assertTrue(plugin.sync_status_api()["data"]["scan_running"])
            self.assertFalse(plugin.stop_service())
            self.assertIsNotNone(plugin._task_store)
            self.assertIsNotNone(plugin._state_store)
            release.set()

        self.assertTrue(self.wait_until(lambda: not plugin.sync_status_api()["data"]["scan_running"]))
        self.assertTrue(plugin.stop_service())
        self.assertIsNone(plugin._task_store)
        self.assertIsNone(plugin._state_store)

    def test_reliable_scan_counts_job_before_immediate_engine_completion(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        (source / "movie.mkv").write_bytes(b"movie")

        class ImmediateEngine:
            def __init__(self, owner):
                self.owner = owner

            def enqueue(self, monitor_root, path, action, payload=None):
                job = type("Job", (), {"payload": payload or {}})()
                self.owner._complete_reliable_job(
                    job,
                    {"status": "processed", "result_statuses": ["generated_strm"]},
                )
                return True

            def snapshot(self):
                return {"memory_queued": 0, "inflight": 0, "scheduled": 0, "workers": 0}

            def stop(self):
                pass

        plugin._reliable_engine = True
        plugin._sync_engine = ImmediateEngine(plugin)

        self.assertTrue(plugin.scan("manual_full"))
        status = plugin.sync_status_api()["data"]
        self.assertFalse(status["scan_running"])
        self.assertEqual(status["recent_runs"][0]["queued"], 1)
        self.assertEqual(status["recent_runs"][0]["processed"], 1)

    def test_subtitle_formats_are_loaded_and_returned_by_form(self):
        plugin = self.make_plugin(self.new_temp() / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "subtitle_formats": ".srt, .vtt",
            }
        )
        self.assertEqual(plugin._subtitle_extensions, {".srt", ".vtt"})
        plugin.get_config = lambda: {"subtitle_formats": ".srt, .vtt"}
        _, model = plugin.get_form()
        self.assertEqual(model["subtitle_formats"], ".srt, .vtt")

    def test_result_status_aliases_use_only_user_facing_categories(self):
        self.assertEqual(
            CloudStrmButler._normalise_result_statuses(["skipped", "generated_strm", "legacy"]),
            {"existing_skipped": 2, "generated_strm": 1},
        )

    def test_status_distinguishes_enabled_idle_plugin_from_orphaned_queue(self):
        base = self.new_temp()
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin({"enabled": True, "monitor": False})
        plugin._task_store.enqueue("/media", "/media/old.mkv", "sync")

        status = plugin.sync_status_api()["data"]

        self.assertTrue(status["enabled"])
        self.assertFalse(status["service_running"])
        self.assertFalse(status["queue_active"])
        self.assertEqual(status["queued"], 1)
        self.assertEqual(status["active_queued"], 0)
        self.assertEqual(status["pending_jobs"], 1)
        self.assertEqual(status["orphaned_queued"], 1)

    def test_status_names_active_monitor_as_idle_monitoring(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": True,
                "monitor": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )

        status = plugin.sync_status_api()["data"]

        self.assertTrue(status["service_running"])
        self.assertTrue(status["monitor_active"])
        self.assertEqual(status["service_state"], "monitoring_idle")

    def test_orphaned_queue_is_visible_even_when_monitor_is_active(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": True,
                "monitor": True,
                "reliable_engine": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        plugin._task_store.enqueue("/media", "/media/old.mkv", "sync")

        status = plugin.sync_status_api()["data"]

        self.assertTrue(status["monitor_active"])
        self.assertEqual(status["service_state"], "pending_recovery")
        self.assertEqual(status["orphaned_queued"], 1)

    def test_full_scan_is_recorded_without_reliable_engine(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "reliable_engine": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        (source / "movie.mkv").write_bytes(b"movie")

        plugin.scan()

        run = plugin.sync_status_api()["data"]["recent_runs"][0]
        self.assertEqual(run["kind"], "scan")
        self.assertEqual(run["queued"], 1)
        self.assertEqual(run["processed"], 1)
        self.assertEqual(run["status"], "completed")

    def test_status_exposes_processing_overview_counts(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "copy_subtitles": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        media_file.write_bytes(b"movie")
        (source / "movie.nfo").write_text("nfo", encoding="utf-8")
        (source / "movie.srt").write_text("subtitle", encoding="utf-8")

        result = plugin._CloudStrmButler__handle_file(str(media_file), str(source))
        self.assertEqual(result["status"], "processed")

        overview = plugin.sync_status_api()["data"]["processing_overview"]

        self.assertEqual(overview["media_total"], 1)
        self.assertEqual(overview["strm_total"], 1)
        self.assertTrue(overview["media_strm_consistent"])
        self.assertEqual(overview["non_media_total"], 1)
        self.assertEqual(overview["non_media_completed"], 1)
        self.assertEqual(overview["subtitle_total"], 1)
        self.assertEqual(overview["subtitle_completed"], 1)

    def test_processing_overview_refresh_counts_media_sidecars_and_invalidates_after_processing(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "copy_subtitles": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )

        first = plugin.sync_status_api()["data"]["processing_overview"]
        self.assertFalse(first["ready"])
        self.assertTrue(self.wait_until(lambda: plugin.sync_status_api()["data"]["processing_overview"]["ready"]))
        self.assertEqual(plugin.sync_status_api()["data"]["processing_overview"]["media_total"], 0)

        media_file = source / "movie.mkv"
        (source / "movie.nfo").write_text("nfo", encoding="utf-8")
        (source / "movie.srt").write_text("subtitle", encoding="utf-8")
        media_file.write_bytes(b"movie")
        plugin._CloudStrmButler__handle_file(str(media_file), str(source))

        def refreshed():
            overview = plugin.sync_status_api()["data"]["processing_overview"]
            return overview["ready"] and overview["media_total"] == 1 and overview["strm_total"] == 1

        self.assertTrue(self.wait_until(refreshed))
        overview = plugin.sync_status_api()["data"]["processing_overview"]
        self.assertEqual(overview["non_media_total"], 1)
        self.assertEqual(overview["non_media_completed"], 1)
        self.assertEqual(overview["subtitle_total"], 1)
        self.assertEqual(overview["subtitle_completed"], 1)

    def test_processing_overview_does_not_double_count_sidecars_after_full_scan(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "copy_subtitles": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        (source / "movie.mkv").write_bytes(b"movie")
        (source / "movie.nfo").write_text("nfo", encoding="utf-8")
        (source / "movie.srt").write_text("subtitle", encoding="utf-8")

        plugin.scan("manual_full")
        overview = plugin.sync_status_api()["data"]["processing_overview"]

        self.assertEqual(overview["media_total"], 1)
        self.assertEqual(overview["strm_total"], 1)
        self.assertEqual(overview["non_media_total"], 1)
        self.assertEqual(overview["non_media_completed"], 1)
        self.assertEqual(overview["subtitle_total"], 1)
        self.assertEqual(overview["subtitle_completed"], 1)

    def test_full_scan_counts_media_sidecars_once(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "copy_subtitles": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        (source / "movie.mkv").write_bytes(b"movie")
        (source / "movie.nfo").write_text("nfo", encoding="utf-8")
        (source / "movie.srt").write_text("subtitle", encoding="utf-8")

        plugin.scan("manual_full")
        run = plugin.sync_status_api()["data"]["recent_runs"][0]

        self.assertEqual(run["result_counts"]["generated_strm"], 1)
        self.assertEqual(run["result_counts"]["copied_non_media"], 1)
        self.assertEqual(run["result_counts"]["copied_subtitle"], 1)
        self.assertEqual(run["result_counts"]["existing_skipped"], 0)

    def test_full_scan_sidecar_result_is_stable_when_directory_lists_sidecar_first(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "copy_subtitles": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        (source / "movie.mkv").write_bytes(b"movie")
        (source / "movie.nfo").write_text("nfo", encoding="utf-8")
        (source / "movie.srt").write_text("subtitle", encoding="utf-8")

        walked = [(str(source), [], ["movie.nfo", "movie.srt", "movie.mkv"])]
        with patch("os.walk", return_value=walked):
            plugin.scan("manual_full")

        run = plugin.sync_status_api()["data"]["recent_runs"][0]
        self.assertEqual(run["result_counts"]["generated_strm"], 1)
        self.assertEqual(run["result_counts"]["copied_non_media"], 1)
        self.assertEqual(run["result_counts"]["copied_subtitle"], 1)

    def test_full_scan_refreshes_changed_sidecar_without_media_change(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "copy_files": True,
                "copy_subtitles": True,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        sidecar = source / "movie.srt"
        media_file.write_bytes(b"movie")
        sidecar.write_text("old", encoding="utf-8")
        plugin.scan("manual_full")
        self.assertEqual((target / "movie.srt").read_text(encoding="utf-8"), "old")

        sidecar.write_text("new subtitle", encoding="utf-8")
        plugin.scan("manual_full")

        self.assertEqual(
            (target / "movie.srt").read_text(encoding="utf-8"),
            "new subtitle",
        )

    def test_full_scan_api_runs_in_background_and_skips_existing_outputs(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        media_file = source / "movie.mkv"
        media_file.write_bytes(b"movie")
        first = plugin._CloudStrmButler__handle_file(str(media_file), str(source))
        self.assertEqual(first["status"], "processed")

        response = plugin.sync_full_scan_api({})

        self.assertEqual(response["code"], 0)
        self.assertTrue(self.wait_until(lambda: not plugin.sync_status_api()["data"]["scan_running"]))
        run = plugin.sync_status_api()["data"]["recent_runs"][0]
        self.assertEqual(run["kind"], "manual_full")
        self.assertGreaterEqual(run["result_counts"]["existing_skipped"], 1)
        self.assertEqual(run["result_counts"]["generated_strm"], 0)

    def test_full_scan_skips_existing_strm_and_generates_missing_strm(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        existing_file = source / "existing.mkv"
        missing_file = source / "missing.mkv"
        existing_file.write_bytes(b"existing")
        missing_file.write_bytes(b"missing")
        first = plugin._CloudStrmButler__handle_file(str(existing_file), str(source))
        self.assertEqual(first["status"], "processed")

        response = plugin.sync_full_scan_api({})

        self.assertEqual(response["code"], 0)
        self.assertTrue(self.wait_until(lambda: not plugin.sync_status_api()["data"]["scan_running"]))
        run = plugin.sync_status_api()["data"]["recent_runs"][0]
        self.assertGreaterEqual(run["result_counts"]["existing_skipped"], 1)
        self.assertGreaterEqual(run["result_counts"]["generated_strm"], 1)
        self.assertTrue((target / "existing.strm").is_file())
        self.assertTrue((target / "missing.strm").is_file())

    def test_full_scan_api_rejects_manual_command_overlap(self):
        plugin = self.make_plugin(self.new_temp() / "data")
        plugin.init_plugin({"enabled": False})
        plugin._command_running = True

        response = plugin.sync_full_scan_api({})

        self.assertNotEqual(response["code"], 0)
        self.assertIn("执行", response["msg"])

    def test_manual_command_rejects_full_scan_overlap(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        (source / "movie.mkv").write_bytes(b"movie")
        plugin._scan_running = True

        plugin.remote_sync_one(
            FakeEvent(
                {
                    "action": "strm_one",
                    "arg_str": str(source),
                    "user": "user-1",
                    "channel": "channel-1",
                }
            )
        )

        self.assertTrue(self.wait_until(lambda: len(plugin.messages) == 1))
        self.assertIn("无法执行", plugin.messages[0]["title"])
        plugin._scan_running = False

    def test_scan_without_task_store_finishes_progress(self):
        plugin = self.make_plugin(self.new_temp() / "data")
        plugin.init_plugin({"enabled": False})
        plugin._task_store = None

        self.assertTrue(plugin.scan("manual_full"))
        self.assertFalse(plugin.sync_status_api()["data"]["scan_progress"]["running"])

    def test_remote_command_reports_missing_path_as_failure(self):
        base = self.new_temp()
        source, target, cloud = self.make_rule_paths(base)
        plugin = self.make_plugin(base / "data")
        plugin.init_plugin(
            {
                "enabled": False,
                "monitor_confs": f"{source}#{target}#{cloud}#{{cloud_file}}",
            }
        )
        missing = source / "missing-folder"

        plugin.remote_sync_one(
            FakeEvent(
                {
                    "action": "strm_one",
                    "arg_str": str(missing),
                    "user": "user-1",
                    "channel": "channel-1",
                }
            )
        )

        self.assertTrue(self.wait_until(lambda: len(plugin.messages) == 1))
        self.assertEqual(len(plugin.messages), 1)
        self.assertIn("失败", plugin.messages[0]["title"])
        self.assertIn("不存在", plugin.messages[0]["title"])


if __name__ == "__main__":
    unittest.main()
