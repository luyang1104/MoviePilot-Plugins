import unittest

from tests.stubs import load_plugin_module

load_plugin_module()

from cloudstrmbutler.config_rules import (
    MonitorRule,
    parse_comma_path_mappings,
    parse_monitor_confs,
    parse_path_mappings,
    serialize_path_mappings,
    rules_to_text,
)


class ConfigRulesTests(unittest.TestCase):
    def test_parse_valid_rules_and_overrides(self):
        text = "\n".join(
            [
                "# comment",
                r"C:\media#C:\library#D:\cloud#{cloud_file}@series$monitor",
                r"C:\movies#C:\out#D:\cloud#{local_file}",
                "",
            ]
        )
        rules, errors = parse_monitor_confs(text)
        self.assertEqual(errors, [])
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0].category, "series")
        self.assertEqual(rules[0].monitor_override, "monitor")
        self.assertTrue(rules[0].should_monitor(False))
        self.assertFalse(rules[1].should_monitor(False))
        self.assertTrue(rules[1].should_monitor(True))

    def test_parse_reports_malformed_and_missing_template(self):
        rules, errors = parse_monitor_confs(
            r"C:\media#C:\out#D:\cloud#literal"
        )
        self.assertEqual(rules, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("STRM", errors[0])

    def test_nested_strm_directory_is_not_a_rule(self):
        rules, errors = parse_monitor_confs(
            r"C:\media#C:\media\strm#D:\cloud#{cloud_file}"
        )
        self.assertEqual(rules, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("子目录", errors[0])

    def test_round_trip_text_and_mappings(self):
        rule = MonitorRule(
            local_dir=r"C:\media",
            strm_dir=r"C:\out",
            cloud_dir=r"D:\cloud",
            format_str="{cloud_file}",
            category="movies",
            monitor_override="nomonitor",
        )
        parsed, errors = parse_monitor_confs(rules_to_text([rule]))
        self.assertEqual(errors, [])
        self.assertEqual(parsed, [rule])

        mappings = [(r"C:\source", r"D:\target"), ("/tmp/a", "/tmp/b")]
        text = serialize_path_mappings(mappings)
        self.assertEqual(parse_path_mappings(text), mappings)

    def test_comma_mappings_accept_arrow_syntax(self):
        self.assertEqual(
            parse_comma_path_mappings(r"C:\source=>D:\target,/mnt/a=>/mnt/b"),
            [(r"C:\source", r"D:\target"), ("/mnt/a", "/mnt/b")],
        )


if __name__ == "__main__":
    unittest.main()
