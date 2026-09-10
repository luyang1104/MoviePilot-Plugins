"""payloads 模块单元测试：webhook 松散字段归一化。"""

import unittest

from tests.stubs import MediaType, WebhookEventInfo, load_plugin_module

plugin_module = load_plugin_module()
payloads = plugin_module.payloads


class NormalizeBoolTests(unittest.TestCase):
    """item_isvirtual 等松散布尔字段的归一化契约（issue #359 的核心防线）。"""

    def test_truthy_values(self):
        for value in ("True", "true", " true ", "1", "yes", "YES", "y", "on", True, 1):
            self.assertIs(payloads.normalize_bool(value), True, f"值 {value!r} 应判真")

    def test_falsy_values(self):
        for value in ("False", "false", " FALSE ", "0", "no", "n", "off", False, 0):
            self.assertIs(payloads.normalize_bool(value), False, f"值 {value!r} 应判假")

    def test_unrecognized_returns_none(self):
        """None、空串、未知文本一律返回 None，由调用方走保护逻辑。"""
        for value in (None, "", "banana"):
            self.assertIsNone(payloads.normalize_bool(value), f"值 {value!r} 应无法识别")


class PathTests(unittest.TestCase):
    def test_windows_path_normalized(self):
        self.assertEqual(payloads.normalize_path("C:\\test\\a.mkv"), "C:/test/a.mkv")

    def test_none_path_becomes_empty(self):
        self.assertEqual(payloads.normalize_path(None), "")

    def test_excluded_prefix(self):
        self.assertTrue(payloads.is_excluded_path("/media/a/x.mkv", "/media/a"))
        self.assertFalse(payloads.is_excluded_path("/media/b/x.mkv", "/media/a"))

    def test_excluded_multi_and_empty_segments(self):
        self.assertTrue(payloads.is_excluded_path("/b/x.mkv", "/a, ,/b"))
        self.assertFalse(payloads.is_excluded_path("/b/x.mkv", ""))
        self.assertFalse(payloads.is_excluded_path("", "/a"))

    def test_path_mapping(self):
        mapped = payloads.apply_path_mapping("/data/A/x.mkv", "/data:/mnt/link")
        self.assertEqual(mapped, "/mnt/link/A/x.mkv")

    def test_path_mapping_skips_invalid_lines(self):
        self.assertEqual(payloads.apply_path_mapping("/a/x.mkv", "no-colon-line\n/a:/b"), "/b/x.mkv")
        self.assertEqual(payloads.apply_path_mapping("/a/x.mkv", ""), "/a/x.mkv")


class MediaTypeTests(unittest.TestCase):
    def test_movie_markers(self):
        for value in ("Movie", "MOV"):
            self.assertEqual(payloads.as_media_type(value), MediaType.MOVIE)

    def test_everything_else_is_tv(self):
        for value in ("Series", "Season", "Episode", "电影", None):
            self.assertEqual(payloads.as_media_type(value), MediaType.TV)


class ParseDeleteTimeTests(unittest.TestCase):
    def test_emby_date(self):
        result = payloads.parse_delete_time({"Date": "2026-09-09T16:27:36.0000000Z"})
        self.assertIsNotNone(result)

    def test_jellyfin_utc_timestamp(self):
        result = payloads.parse_delete_time({"UtcTimestamp": "2026-09-09T16:27:36.0000000Z"})
        self.assertIsNotNone(result)

    def test_missing_or_garbage_returns_none(self):
        for payload in ({}, None, {"Date": "不是时间"}, "raw-string"):
            self.assertIsNone(payloads.parse_delete_time(payload), f"负载 {payload!r} 应返回 None")


class RequestBuilderTests(unittest.TestCase):
    def test_webhook_request(self):
        event = WebhookEventInfo(
            media_type="Movie", item_name="测试", item_path="D:\\x\\a.mkv",
            season_id=None, episode_id=None, media_source=None, media_id="42",
            json_object={"Date": "2026-09-09T16:27:36.0000000Z"},
        )
        request = payloads.build_webhook_request(event)
        self.assertEqual(request.media_type, "Movie")
        self.assertEqual(request.media_path, "D:/x/a.mkv")
        self.assertIsNotNone(request.delete_time)

    def test_scripterx_request_uses_item_type(self):
        event = WebhookEventInfo(
            item_type="Episode", item_name="测试", item_path="/x/e01.mkv",
            season_id="1", episode_id="1", media_source=None, media_id="42",
        )
        request = payloads.build_scripterx_request(event)
        self.assertEqual(request.media_type, "Episode")
        self.assertIsNone(request.delete_time)

    def test_action_request(self):
        request = payloads.build_action_request({
            "media_type": "Series", "media_name": "测试", "media_path": None,
            "media_id": "42", "season_num": "2",
        })
        self.assertEqual(request.media_path, "")
        self.assertEqual(request.season_num, "2")


class ScripterXHardeningTests(unittest.TestCase):
    """无法识别的 item_isvirtual（非 None 的未知值）也必须触发保护，不得放行删除。"""

    def test_garbage_isvirtual_disables_plugin(self):
        from tests.stubs import FakeEvent, eventmanager, logger
        logger.clear()
        eventmanager.sent_events.clear()
        plugin = plugin_module.LinkedMediaDel()
        plugin.init_plugin({
            "enabled": True, "sync_type": "plugin", "notify": False,
            "del_source": False, "del_history": False, "library_path": "", "exclude_path": "",
        })
        event = WebhookEventInfo(
            event="media_del", item_type="Movie", item_name="测试", item_path="/x/a.mkv",
            item_isvirtual="不是布尔值",
        )
        plugin.sync_del_by_plugin(FakeEvent(event_data=event))
        self.assertTrue(any("item_isvirtual" in m for m in logger.messages("error")))
        self.assertFalse(plugin._stored_config.get("enabled", True))
        self.assertFalse(any("未获取到可删除数据" in m for m in logger.messages("warning")))


if __name__ == "__main__":
    unittest.main()
