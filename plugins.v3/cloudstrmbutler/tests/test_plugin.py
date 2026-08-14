import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.stubs import load_plugin_module

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
            ["/sync_status", "/sync_failures", "/sync_retry_failure", "/sync_confirm_cleanup"],
        )

    def test_status_api_paths_use_moviepilot_plugin_id_case(self):
        page_source = (Path(__file__).resolve().parent.parent / "src" / "Page.vue").read_text(encoding="utf-8")

        self.assertIn("plugin/CloudStrmButler/sync_status", page_source)
        self.assertIn("plugin/CloudStrmButler/sync_failures", page_source)
        self.assertNotIn("plugin/cloudstrmbutler/", page_source)

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


if __name__ == "__main__":
    unittest.main()
