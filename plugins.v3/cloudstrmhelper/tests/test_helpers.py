"""Unit tests for the dependency-free CloudStrm helper modules."""

from __future__ import annotations

import importlib.util
import tempfile
import sys
import types
import unittest
from pathlib import Path


PACKAGE_NAME = "_cloudstrmhelper_test_package"
PACKAGE_DIR = Path(__file__).resolve().parents[1]

package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PACKAGE_DIR)]
sys.modules[PACKAGE_NAME] = package


def load_module(name: str):
    full_name = f"{PACKAGE_NAME}.{name}"
    spec = importlib.util.spec_from_file_location(
        full_name, PACKAGE_DIR / f"{name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


paths = load_module("paths")
rules = load_module("rules")
manifest_module = load_module("manifest")


class PathHelperTests(unittest.TestCase):
    def test_windows_mapping_keeps_drive_colon(self):
        self.assertEqual(
            paths.parse_mapping_line(r"C:\source:C:\target"),
            (r"C:\source", r"C:\target"),
        )

    def test_path_boundary_does_not_match_sibling(self):
        self.assertTrue(paths.is_path_within("/media/movies/a.mkv", "/media/movies"))
        self.assertFalse(paths.is_path_within("/media/movies2/a.mkv", "/media/movies"))

    def test_format_content_supports_plain_and_encoded_cloud_paths(self):
        self.assertEqual(
            paths.format_content("http://openlist/d{cloud_file}", "/local/a.mkv", "电影/a.mkv", False),
            "http://openlist/d电影/a.mkv",
        )
        self.assertEqual(
            paths.format_content("http://openlist/d{cloud_file}", "/local/a.mkv", "电影/a.mkv", True),
            "http://openlist/d%E7%94%B5%E5%BD%B1%2Fa.mkv",
        )
        self.assertIsNone(paths.format_content("http://openlist/file", "/local/a.mkv", "cloud", False))


class RuleHelperTests(unittest.TestCase):
    def test_legacy_rules_round_trip(self):
        raw = "/local# /strm # /cloud #http://x/{cloud_file}@电影,剧集$0"
        parsed = rules.rules_from_monitor_confs(raw)
        self.assertEqual(parsed[0]["category"], "电影,剧集")
        self.assertFalse(parsed[0]["monitor"])
        self.assertEqual(rules.rules_to_monitor_confs(parsed), raw.replace("# ", "#").replace(" #", "#"))

    def test_structured_slots_are_authoritative_when_deleted(self):
        config = {
            "monitor_confs": "/old#old#old#http://x/{cloud_file}",
            "rule_0_local": "/local",
            "rule_0_strm": "/strm",
            "rule_0_delete": True,
        }
        self.assertEqual(rules.rules_from_config(config), [])

    def test_blank_add_slot_falls_back_to_legacy_rules(self):
        config = {
            "monitor_confs": "/old#old-strm#/cloud#http://x/{cloud_file}",
            "rule_0_local": "",
            "rule_0_strm": "",
        }
        rules_out = rules.rules_from_config(config)
        self.assertEqual(len(rules_out), 1)
        self.assertEqual(rules_out[0]["local"], "/old")

    def test_rule_keys_clear_old_slots(self):
        config = {
            "rule_0_local": "/old",
            "rule_0_strm": "/old-strm",
            "rule_1_format": "old",
            "keep": "value",
        }
        rules.remove_rule_config_keys(config)
        self.assertEqual(config, {"keep": "value"})


class ManifestTests(unittest.TestCase):
    def test_manifest_round_trip_uses_normalized_unique_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "generated_files.json"
            manifest_module.GeneratedFileManifest.save(
                str(manifest_path),
                [str(Path(directory) / "nested" / ".." / "a.strm"),
                 str(Path(directory) / "a.strm")],
            )
            loaded = manifest_module.GeneratedFileManifest.load(str(manifest_path))
            self.assertEqual(len(loaded), 1)
            self.assertIn(str(Path(directory) / "a.strm").lower(), loaded)


if __name__ == "__main__":
    unittest.main()

class SourceRegressionTests(unittest.TestCase):
    """Static checks that the dashboard keeps real controls and drops dead code."""

    @classmethod
    def setUpClass(cls):
        cls.source = (PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8")

    def test_dashboard_has_no_decorative_pointer_only_controls(self):
        self.assertNotIn("cursor:pointer", self.source)

    def test_settings_form_has_no_client_side_show_hack(self):
        self.assertNotIn("mapping_new_rule_visible", self.source)
        self.assertNotIn('"onClick"', self.source)

    def test_dead_legacy_code_is_removed(self):
        for marker in ("__sava_json", "export_dir", "__handle_limit",
                       "__legacy_get_form", "metric_card", "_cloud_files"):
            self.assertNotIn(marker, self.source)

    def test_version_is_v160(self):
        self.assertIn('plugin_version = "V1.6.0"', self.source)
