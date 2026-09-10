"""入口级表征测试：锁定重构前的对外行为。

全部通过插件公开事件入口驱动，断言日志、外发事件与配置副作用，
不触碰内部私有方法，保证模块拆分后依旧适用。
"""

import unittest

from tests.stubs import (
    FakeEvent,
    FakeTransferHistoryOper,
    MediaSource,
    TransferRecord,
    WebhookEventInfo,
    eventmanager,
    load_plugin_module,
    logger,
)

plugin_module = load_plugin_module()
LinkedMediaDel = plugin_module.LinkedMediaDel

BASE_CONFIG = {
    "enabled": True,
    "notify": False,
    "del_source": False,
    "del_history": False,
    "library_path": "",
    "exclude_path": "",
}


def make_plugin(sync_type="plugin", **overrides):
    config = dict(BASE_CONFIG, sync_type=sync_type, **overrides)
    plugin = LinkedMediaDel()
    plugin.init_plugin(config)
    return plugin


def scripterx_event(**overrides):
    data = WebhookEventInfo(
        event="media_del",
        item_type="Episode",
        item_name="__自检不存在媒体__",
        item_path="/media/tv/x/S01E01.mkv",
        season_id="1",
        episode_id="1",
        media_source=MediaSource.TMDB,
        media_id="999999999",
        item_isvirtual="False",
    )
    data.__dict__.update(overrides)
    return FakeEvent(event_data=data)


def emby_webhook_event(**overrides):
    data = WebhookEventInfo(
        event="library.deleted",
        media_type="Movie",
        item_name="__自检不存在媒体__",
        item_path="/media/movies/x.mkv",
        media_source=MediaSource.TMDB,
        media_id="999999999",
        json_object={"Date": "2026-09-09T16:27:36.0000000Z"},
    )
    data.__dict__.update(overrides)
    return FakeEvent(event_data=data)


class ScripterXFlowTests(unittest.TestCase):
    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()

    def test_isvirtual_string_false_enters_deletion(self):
        """item_isvirtual='False'（字符串）必须进入删除逻辑（issue #359 回归）。"""
        plugin = make_plugin()
        plugin.sync_del_by_plugin(scripterx_event())
        self.assertTrue(
            any("未获取到可删除数据" in m for m in logger.messages("warning")),
            f"应进入删除逻辑，日志：{logger.records}",
        )

    def test_isvirtual_lowercase_false_enters_deletion(self):
        plugin = make_plugin()
        plugin.sync_del_by_plugin(scripterx_event(item_isvirtual="false"))
        self.assertTrue(any("未获取到可删除数据" in m for m in logger.messages("warning")))

    def test_isvirtual_zero_enters_deletion(self):
        plugin = make_plugin()
        plugin.sync_del_by_plugin(scripterx_event(item_isvirtual="0"))
        self.assertTrue(any("未获取到可删除数据" in m for m in logger.messages("warning")))

    def test_isvirtual_bool_false_enters_deletion(self):
        plugin = make_plugin()
        plugin.sync_del_by_plugin(scripterx_event(item_isvirtual=False))
        self.assertTrue(any("未获取到可删除数据" in m for m in logger.messages("warning")))

    def test_isvirtual_true_skips_with_log(self):
        """虚拟 item 必须跳过，且跳过要有日志（不允许静默 return）。"""
        plugin = make_plugin()
        plugin.sync_del_by_plugin(scripterx_event(item_isvirtual="True"))
        self.assertFalse(any("未获取到可删除数据" in m for m in logger.messages("warning")))
        self.assertFalse(any("开始同步删除" in m for m in logger.messages()))

    def test_isvirtual_bool_true_skips(self):
        plugin = make_plugin()
        plugin.sync_del_by_plugin(scripterx_event(item_isvirtual=True))
        self.assertFalse(any("未获取到可删除数据" in m for m in logger.messages("warning")))

    def test_isvirtual_none_disables_plugin(self):
        """item_isvirtual 为 None 时防误删：报错并自动停用插件。"""
        plugin = make_plugin()
        plugin.sync_del_by_plugin(scripterx_event(item_isvirtual=None))
        self.assertTrue(any("item_isvirtual" in m for m in logger.messages("error")))
        self.assertFalse(any("未获取到可删除数据" in m for m in logger.messages("warning")))
        self.assertFalse(plugin._stored_config.get("enabled", True))

    def test_wrong_sync_type_ignores_event(self):
        plugin = make_plugin(sync_type="webhook")
        plugin.sync_del_by_plugin(scripterx_event())
        self.assertFalse(any("未获取到可删除数据" in m for m in logger.messages("warning")))

    def test_disabled_plugin_ignores_event(self):
        plugin = make_plugin(enabled=False)
        plugin.sync_del_by_plugin(scripterx_event())
        self.assertEqual(logger.records, [])

    def test_other_event_type_ignores(self):
        plugin = make_plugin()
        plugin.sync_del_by_plugin(scripterx_event(event="library.deleted"))
        self.assertFalse(any("未获取到可删除数据" in m for m in logger.messages("warning")))

    def test_missing_identity_blocks_deletion(self):
        plugin = make_plugin()
        plugin.sync_del_by_plugin(scripterx_event(media_source=None, media_id=None))
        self.assertTrue(any("未获取到有效媒体身份" in m for m in logger.messages("error")))
        self.assertFalse(any("未获取到可删除数据" in m for m in logger.messages("warning")))


class WebhookFlowTests(unittest.TestCase):
    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()

    def test_library_deleted_enters_deletion(self):
        plugin = make_plugin(sync_type="webhook")
        plugin.sync_del_by_webhook(emby_webhook_event())
        self.assertTrue(any("未获取到可删除数据" in m for m in logger.messages("warning")))

    def test_jellyfin_item_deleted_enters_deletion(self):
        """既有 Jellyfin 顺带兼容（ItemDeleted + UtcTimestamp）保持不变。"""
        plugin = make_plugin(sync_type="webhook")
        plugin.sync_del_by_webhook(
            emby_webhook_event(
                event="ItemDeleted",
                json_object={"UtcTimestamp": "2026-09-09T16:27:36.0000000Z"},
            )
        )
        self.assertTrue(any("未获取到可删除数据" in m for m in logger.messages("warning")))

    def test_other_event_type_ignores(self):
        plugin = make_plugin(sync_type="webhook")
        plugin.sync_del_by_webhook(emby_webhook_event(event="playback.start"))
        self.assertFalse(any("未获取到可删除数据" in m for m in logger.messages("warning")))

    def test_windows_path_normalized(self):
        """Windows 反斜杠路径被归一化为 / 后再处理。"""
        plugin = make_plugin(sync_type="webhook")
        plugin.sync_del_by_webhook(emby_webhook_event(item_path="D:\\media\\x.mkv"))
        self.assertTrue(any("未获取到可删除数据" in m for m in logger.messages("warning")))

    def test_missing_identity_blocks_deletion(self):
        plugin = make_plugin(sync_type="webhook")
        plugin.sync_del_by_webhook(emby_webhook_event(media_source=None, media_id=None))
        self.assertTrue(any("未获取到有效媒体身份" in m for m in logger.messages("error")))


class ExcludePathTests(unittest.TestCase):
    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()

    def test_excluded_path_triggers_networkdisk_event(self):
        """命中排除路径：不删除，转发 networkdisk_del 事件给网盘删除插件。"""
        plugin = make_plugin(sync_type="webhook", exclude_path="/media/movies")
        plugin.sync_del_by_webhook(emby_webhook_event())
        self.assertFalse(any("未获取到可删除数据" in m for m in logger.messages("warning")))
        actions = [d for _, d in eventmanager.sent_events if d and d.get("action") == "networkdisk_del"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["media_path"], "/media/movies/x.mkv")

    def test_non_excluded_path_proceeds(self):
        plugin = make_plugin(sync_type="webhook", exclude_path="/other")
        plugin.sync_del_by_webhook(emby_webhook_event())
        self.assertTrue(any("未获取到可删除数据" in m for m in logger.messages("warning")))


class PluginActionQueryTests(unittest.TestCase):
    """经 PluginAction 入口锁定转移历史查询的组装行为。"""

    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()
        self.plugin = make_plugin()
        self.transferhis = FakeTransferHistoryOper()
        self.plugin._transferhis = self.transferhis
        self.plugin._deleter._transferhis = self.transferhis

    def fire(self, **event_data):
        data = {
            "action": "media_sync_del",
            "media_type": "Movie",
            "media_name": "测试",
            "media_path": "",
            "media_source": MediaSource.TMDB,
            "media_id": "12345",
        }
        data.update(event_data)
        self.plugin.sync_del(FakeEvent(event_data=data))
        return self.transferhis.get_by_calls

    def test_movie_query(self):
        calls = self.fire()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["mtype"], "电影")
        self.assertEqual(calls[0]["media_id"], "12345")
        self.assertIn("dest", calls[0])

    def test_series_query(self):
        calls = self.fire(media_type="Series")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["mtype"], "电视剧")
        self.assertNotIn("season", calls[0])

    def test_season_query_padded(self):
        calls = self.fire(media_type="Series", season_num="2")
        self.assertEqual(calls[0]["season"], "S02")
        self.assertNotIn("episode", calls[0])

    def test_episode_query_padded(self):
        calls = self.fire(media_type="Episode", season_num=2, episode_num=3, media_path="/x/e03.mkv")
        self.assertEqual(calls[0]["season"], "S02")
        self.assertEqual(calls[0]["episode"], "E03")
        self.assertEqual(calls[0]["dest"], "/x/e03.mkv")

    def test_invalid_season_blocks_query(self):
        calls = self.fire(media_type="Series", season_num="abc")
        self.assertEqual(calls, [])
        self.assertTrue(any("季编号格式无效" in m for m in logger.messages("error")))

    def test_episode_without_season_blocks_query(self):
        calls = self.fire(media_type="Episode", episode_num="3")
        self.assertEqual(calls, [])
        self.assertTrue(any("集编号格式无效" in m for m in logger.messages("error")))

    def test_missing_media_type_blocks(self):
        self.plugin.sync_del(FakeEvent(event_data={
            "action": "media_sync_del", "media_name": "测试", "media_source": MediaSource.TMDB,
            "media_id": "1",
        }))
        self.assertTrue(any("未获取到媒体类型" in m for m in logger.messages("error")))
        self.assertEqual(self.transferhis.get_by_calls, [])

    def test_wrong_action_ignores(self):
        self.plugin.sync_del(FakeEvent(event_data={"action": "other_action"}))
        self.assertEqual(self.transferhis.get_by_calls, [])


class DeleteExecutionTests(unittest.TestCase):
    """锁定删除执行的关键安全语义。"""

    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()
        self.plugin = make_plugin()
        self.transferhis = FakeTransferHistoryOper()
        self.plugin._transferhis = self.transferhis
        self.plugin._deleter._transferhis = self.transferhis

    def fire_webhook(self, **overrides):
        self.plugin._sync_type = "webhook"
        self.plugin.sync_del_by_webhook(emby_webhook_event(**overrides))

    def test_existing_media_path_skips(self):
        """转移路径仍存在（重新整理场景）→ 跳过处理。"""
        self.fire_webhook(item_path=".")  # 当前目录必然存在
        self.assertTrue(any("未被删除或重新生成" in m for m in logger.messages("warning")))
        self.assertEqual(self.transferhis.get_by_calls, [])

    def test_title_mismatch_protects_history(self):
        """转移记录标题与删除媒体不符 → 防误删，保留历史。"""
        record = TransferRecord(
            id=1, title="别的标题", type="电影", year="2024",
            src="", dest="/media/movies/x.mkv", media_source=MediaSource.TMDB, media_id="999999999",
            date="2026-09-01 00:00:00",
        )
        self.transferhis.records.append(record)
        self.fire_webhook()
        self.assertTrue(any("防误删" in m for m in logger.messages("warning")))
        self.assertEqual(self.transferhis.deleted_ids, [])

    def test_matching_title_deletes_history(self):
        record = TransferRecord(
            id=2, title="__自检不存在媒体__", type="电影", year="2024",
            src="", dest="/media/movies/x.mkv", media_source=MediaSource.TMDB, media_id="999999999",
            date="2026-09-01 00:00:00",
        )
        self.transferhis.records.append(record)
        self.fire_webhook()
        self.assertEqual(self.transferhis.deleted_ids, [2])
        history = self.plugin.get_data("history")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["media_source"], "themoviedb")

    def test_delete_time_older_than_transfer_skips(self):
        """整理时间晚于删除事件时间 → 忽略删除。"""
        record = TransferRecord(
            id=3, title="__自检不存在媒体__", type="电影", year="2024",
            src="", dest="/media/movies/x.mkv", media_source=MediaSource.TMDB, media_id="999999999",
            date="2026-09-11 00:00:01",
        )
        self.transferhis.records.append(record)
        self.fire_webhook()  # Date = 2026-09-09T16:27:36Z
        self.assertTrue(any("忽略删除" in m for m in logger.messages("warning")))
        self.assertEqual(self.transferhis.deleted_ids, [])


if __name__ == "__main__":
    unittest.main()
