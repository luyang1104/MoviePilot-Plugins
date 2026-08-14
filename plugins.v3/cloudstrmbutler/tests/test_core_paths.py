import os
import unittest
from pathlib import Path

from tests.stubs import ROOT, load_plugin_module

load_plugin_module()

from cloudstrmbutler.core_paths import (
    find_monitor_path,
    format_content,
    map_library_path,
    map_path,
    normalise_extensions,
    parse_mapping_line,
    path_key,
    relative_path,
)


class CorePathsTests(unittest.TestCase):
    def test_path_key_normalizes_windows_case(self):
        self.assertEqual(path_key(r"C:\Temp\Test"), path_key(r"c:\temp\test"))

    def test_relative_path_rejects_escape(self):
        root = str(ROOT)
        self.assertEqual(relative_path(root, root), Path())
        self.assertIsNone(relative_path(str(ROOT.parent), root))

    def test_map_path_preserves_relative_suffix(self):
        root = r"C:\media"
        target = r"C:\library"
        self.assertEqual(
            map_path(r"C:\media\Series\Show\movie.mkv", root, target),
            r"C:\library\Series\Show\movie.mkv",
        )
        self.assertIsNone(map_path(r"C:\elsewhere\movie.mkv", root, target))

    def test_find_monitor_path_prefers_longest_root(self):
        paths = {r"C:\media": "short", r"C:\media\series": "long"}
        self.assertEqual(find_monitor_path(r"C:\media\series\a.mkv", paths), r"C:\media\series")
        self.assertIsNone(find_monitor_path(r"C:\other\a.mkv", paths))

    def test_parse_mapping_line_supports_arrow_and_windows_colon(self):
        self.assertEqual(parse_mapping_line(r"C:\source=>D:\target"), (r"C:\source", r"D:\target"))
        self.assertEqual(parse_mapping_line(r"C:\source:D:\target"), (r"C:\source", r"D:\target"))

    def test_format_content_replaces_and_encodes_cloud_file(self):
        content = format_content(
            "http://alist/d/{cloud_file}",
            r"C:\media\show.mkv",
            r"/cloud/show.mkv",
            True,
        )
        self.assertEqual(content, "http://alist/d/%2Fcloud%2Fshow.mkv")

    def test_format_content_rejects_missing_cloud_placeholder(self):
        self.assertIsNone(format_content("{cloud_file}", r"C:\media\show.mkv", None, False))

    def test_normalise_extensions(self):
        self.assertEqual(normalise_extensions("mp4, .MKV, nfo"), {".mp4", ".mkv", ".nfo"})

    def test_map_library_path_uses_longest_match(self):
        paths = {r"C:\library": "/library", r"C:\library\movies": "/movies"}
        self.assertEqual(
            map_library_path(paths, r"C:\library\movies\a.mkv"),
            "/movies/a.mkv",
        )


if __name__ == "__main__":
    unittest.main()
