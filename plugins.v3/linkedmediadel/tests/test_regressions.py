"""Bug 修复回归测试：每个用例锁定一个已确认的线上 bug（H1-H3 / M1-M9 / L1 / L4 / M6）。

文件级结论先行：
- H1 空目录回收、M3 单条异常、M7 大写扩展名用真实临时目录验证；
- H2 / H3 / M1 / M2 经插件事件入口驱动，断言查询组装与日志；
- M8 / M9 为 payloads 纯函数；
- M6 / L1 / L4 断言配置副作用、并发落盘与通知文案。
"""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.stubs import (
    FakeEvent,
    FakeTransferHistoryOper,
    MediaSource,
    MediaType,
    StringUtils,
    TransferRecord,
    WebhookEventInfo,
    build_media_key,
    eventmanager,
    load_plugin_module,
    logger,
    resolve_media_identity,
)

plugin_module = load_plugin_module()
LinkedMediaDel = plugin_module.LinkedMediaDel
payloads = plugin_module.payloads

BASE_CONFIG = {
    "enabled": True,
    "notify": False,
    "del_source": False,
    "del_history": False,
    "library_path": "",
    "exclude_path": "",
}


def make_plugin(sync_type="webhook", **overrides):
    config = dict(BASE_CONFIG, sync_type=sync_type, **overrides)
    plugin = LinkedMediaDel()
    plugin.init_plugin(config)
    return plugin


def webhook_event(**overrides):
    data = WebhookEventInfo(
        event="library.deleted",
        media_type="Movie",
        item_name="测试电影",
        item_path="/media/movies/x.mkv",
        media_source=MediaSource.TMDB,
        media_id="999999999",
    )
    data.__dict__.update(overrides)
    return FakeEvent(event_data=data)


def movie_record(**overrides):
    record = TransferRecord(
        id=1, title="测试电影", type="电影", year="2024",
        src="", dest="/media/movies/x.mkv",
        media_source=MediaSource.TMDB, media_id="999999999",
        date="2026-09-10 00:00:00",
    )
    record.__dict__.update(overrides)
    return record


class StubFidelityTests(unittest.TestCase):
    """桩件与真实 MP 行为对齐的锚点（偏差曾掩盖 H3/M1）。"""

    def test_str_to_timestamp_failure_returns_zero(self):
        self.assertEqual(StringUtils.str_to_timestamp("不是时间"), 0)
        self.assertEqual(StringUtils.str_to_timestamp(None), 0)
        self.assertEqual(StringUtils.str_to_timestamp(""), 0)

    def test_build_media_key_uses_tmdb_prefix(self):
        self.assertEqual(build_media_key(MediaSource.TMDB, "123"), "tmdb:123")
        self.assertEqual(build_media_key(None, "123"), "")
        self.assertEqual(build_media_key(MediaSource.TMDB, "0"), "")

    def test_media_source_str_returns_value(self):
        self.assertEqual(str(MediaSource.TMDB), "themoviedb")

    def test_resolve_identity_requires_pair(self):
        self.assertEqual(resolve_media_identity(media_source=MediaSource.TMDB, media_id=None),
                         (None, None))
        self.assertEqual(resolve_media_identity(media_source=None, media_id="123"),
                         (None, None))

    def test_get_by_empty_dest_skips_dest_filter(self):
        """真实 list_by 对空 dest 跳过路径过滤，返回该媒体全部版本。"""
        oper = FakeTransferHistoryOper(records=[
            movie_record(id=1, dest="/a/x.mkv"),
            movie_record(id=2, dest="/b/x.mkv"),
        ])
        result = oper.get_by(media_source=MediaSource.TMDB, media_id="999999999",
                             mtype="电影", dest="")
        self.assertEqual({r.id for r in result}, {1, 2})


class RemoveParentDirTests(unittest.TestCase):
    """H1：空目录回收只删真空目录，上溯遇映射目标根/挂载点/非空目录即停。"""

    def setUp(self):
        logger.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def make_deleter(self, library_path=""):
        return make_plugin(library_path=library_path, del_source=True)._deleter

    def test_non_empty_dir_never_removed(self):
        """目录内有 nfo 等非媒体文件时不得递归强删。"""
        movie_dir = self.root / "movies" / "Movie (2024)"
        movie_dir.mkdir(parents=True)
        (movie_dir / "x.nfo").write_text("meta")
        deleter = self.make_deleter()
        deleter._remove_parent_dir(movie_dir / "x.mkv")  # x.mkv 已被媒体服务器删除
        self.assertTrue((movie_dir / "x.nfo").exists())
        self.assertTrue(movie_dir.exists())
        self.assertTrue((self.root / "movies").exists())
        self.assertTrue(any("非空" in m for m in logger.messages("debug")))

    def test_mapping_dest_root_stops_recursion(self):
        """上溯遇到路径映射目标根（库根）即停。"""
        (self.root / "movies" / "Movie").mkdir(parents=True)
        deleter = self.make_deleter(library_path=f"/media:{self.root}/movies")
        deleter._remove_parent_dir(self.root / "movies" / "Movie" / "x.mkv")
        self.assertFalse((self.root / "movies" / "Movie").exists())
        self.assertTrue((self.root / "movies").exists())
        self.assertTrue(any("路径映射目标根" in m for m in logger.messages("debug")))

    def test_mount_point_stops_recursion(self):
        """上溯遇到挂载点即停。"""
        (self.root / "mnt" / "media" / "Movie").mkdir(parents=True)
        deleter = self.make_deleter()
        mount_dir = str(self.root / "mnt" / "media")
        real_ismount = os.path.ismount
        with mock.patch("os.path.ismount",
                        lambda p: str(p) == mount_dir or real_ismount(p)):
            deleter._remove_parent_dir(self.root / "mnt" / "media" / "Movie" / "x.mkv")
        self.assertFalse((self.root / "mnt" / "media" / "Movie").exists())
        self.assertTrue((self.root / "mnt" / "media").exists())
        self.assertTrue(any("挂载点" in m for m in logger.messages("debug")))

    def test_remaining_media_files_block_recursion(self):
        """父目录仍有媒体文件时不做任何回收。"""
        movie_dir = self.root / "movies" / "Movie"
        movie_dir.mkdir(parents=True)
        (movie_dir / "other.mkv").write_text("video")
        deleter = self.make_deleter()
        deleter._remove_parent_dir(movie_dir / "x.mkv")
        self.assertTrue(movie_dir.exists())
        self.assertTrue(any("仍存在媒体文件" in m for m in logger.messages("debug")))


class SeasonZeroTests(unittest.TestCase):
    """H2：特别篇 season=0（Emby 传 int 0，Scripter X 传字符串 "0"）按第 0 季查询。"""

    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()
        self.plugin = make_plugin()
        self.transferhis = FakeTransferHistoryOper()
        self.plugin._transferhis = self.transferhis
        self.plugin._deleter._transferhis = self.transferhis

    def fire(self, season_id, episode_id=1):
        self.plugin.sync_del_by_webhook(webhook_event(
            media_type="Episode", item_name="某剧",
            item_path="/media/tv/某剧/S00E01.mkv",
            season_id=season_id, episode_id=episode_id,
        ))
        return self.transferhis.get_by_calls

    def test_int_zero_season_queries_s00(self):
        calls = self.fire(0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["season"], "S00")
        self.assertEqual(calls[0]["episode"], "E01")

    def test_string_zero_season_queries_s00(self):
        calls = self.fire("0")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["season"], "S00")

    def test_int_zero_season_only_queries_s00_not_whole_series(self):
        """整季特别篇删除：season=0 无 episode 时必须按季查询，不得退化为整剧。"""
        calls = self.fire(0, episode_id=None)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["season"], "S00")
        self.assertNotIn("episode", calls[0])


class SeasonFallbackTests(unittest.TestCase):
    """M2：Emby 原生 webhook 整季删除（Season 项季号在 IndexNumber）兜底为季号。"""

    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()
        self.plugin = make_plugin()
        self.transferhis = FakeTransferHistoryOper()
        self.plugin._transferhis = self.transferhis
        self.plugin._deleter._transferhis = self.transferhis

    def fire(self, media_type="Season", season_id=None, episode_id=2):
        self.plugin.sync_del_by_webhook(webhook_event(
            media_type=media_type, item_name="某剧",
            item_path="/media/tv/某剧/Season 2",
            season_id=season_id, episode_id=episode_id,
        ))
        return self.transferhis.get_by_calls

    def test_season_payload_episode_used_as_season(self):
        calls = self.fire()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["season"], "S02")
        self.assertNotIn("episode", calls[0])
        self.assertTrue(any("集编号字段" in m for m in logger.messages("info")))

    def test_episode_type_without_season_still_rejected(self):
        """普通单集删除不走兜底：缺季号仍然拒绝。"""
        calls = self.fire(media_type="Episode", episode_id=3)
        self.assertEqual(calls, [])
        self.assertTrue(any("集编号格式无效" in m for m in logger.messages("error")))


class EmptyDestRefusedTests(unittest.TestCase):
    """H3：电影/单集分支空 dest 拒绝执行（真实 list_by 会命中该媒体全部版本）。"""

    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()
        self.plugin = make_plugin()
        self.transferhis = FakeTransferHistoryOper(records=[
            movie_record(id=1, dest="/a/x.mkv"),
            movie_record(id=2, dest="/b/x.mkv"),
        ])
        self.plugin._transferhis = self.transferhis
        self.plugin._deleter._transferhis = self.transferhis

    def fire_action(self, **data):
        payload = {
            "action": "media_sync_del", "media_type": "Movie", "media_name": "测试电影",
            "media_path": "", "media_source": MediaSource.TMDB, "media_id": "999999999",
        }
        payload.update(data)
        self.plugin.sync_del(FakeEvent(event_data=payload))

    def test_movie_empty_dest_refused_with_log(self):
        self.fire_action()
        self.assertEqual(self.transferhis.get_by_calls, [])
        self.assertEqual(self.transferhis.deleted_ids, [])
        self.assertTrue(any("拒绝执行同步删除" in m for m in logger.messages("warning")))

    def test_episode_empty_dest_refused_with_log(self):
        self.fire_action(media_type="Episode", season_num=1, episode_num=3)
        self.assertEqual(self.transferhis.get_by_calls, [])
        self.assertTrue(any("拒绝执行同步删除" in m for m in logger.messages("warning")))


class DeleteTimeTests(unittest.TestCase):
    """M1：垃圾时间字符串跳过时间比较，不退化为 1970 导致删除被永久静默跳过。"""

    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()

    def test_garbage_time_returns_none(self):
        result = payloads.parse_delete_time({"Date": "not-a-date"})
        self.assertIsNone(result)

    def test_garbage_time_never_becomes_epoch(self):
        for payload in ({"Date": "not-a-date"}, {"UtcTimestamp": "垃圾"}):
            result = payloads.parse_delete_time(payload)
            self.assertNotEqual(result, "1970-01-01 08:00:00")
            self.assertIsNone(result)

    def test_garbage_time_skips_comparison_and_deletes(self):
        plugin = make_plugin()
        transferhis = FakeTransferHistoryOper(records=[movie_record(id=9)])
        plugin._transferhis = transferhis
        plugin._deleter._transferhis = transferhis
        plugin.sync_del_by_webhook(webhook_event(json_object={"Date": "not-a-date"}))
        self.assertEqual(transferhis.deleted_ids, [9])
        self.assertFalse(any("忽略删除" in m for m in logger.messages()))


class PerRecordFailureTests(unittest.TestCase):
    """M3：单条记录删除异常不影响后续记录，失败记录保留整理历史。"""

    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # 哨兵文件：阻止空目录回收删掉临时根目录本身
        (self.root / "keep.txt").write_text("keep")
        self.plugin = make_plugin(del_source=True)
        self.transferhis = FakeTransferHistoryOper()
        self.plugin._transferhis = self.transferhis
        self.plugin._deleter._transferhis = self.transferhis

    def fire_series(self):
        self.plugin.sync_del_by_webhook(webhook_event(
            media_type="Series", item_name="测试剧", item_path="/media/tv/测试剧",
        ))

    def test_broken_record_does_not_abort_others(self):
        bad_src = self.root / "src" / "bad.mkv"
        bad_src.mkdir(parents=True)  # 同名目录：unlink 必抛 IsADirectoryError
        ok_src = self.root / "src" / "ok.mkv"
        ok_src.write_text("video")
        self.transferhis.records.extend([
            movie_record(id=1, title="测试剧", type="电视剧", src=str(bad_src), dest=None),
            movie_record(id=2, title="测试剧", type="电视剧", src=str(ok_src),
                         dest="/media/tv/测试剧/ok.mkv"),
        ])
        self.fire_series()
        # 后续记录正常处理
        self.assertEqual(self.transferhis.deleted_ids, [2])
        self.assertFalse(ok_src.exists())
        # 失败记录保留整理历史，且执行有完整收尾（历史落盘）
        self.assertTrue(bad_src.exists())
        self.assertTrue(any("删除媒体文件失败" in m for m in logger.messages("error")))
        self.assertTrue(any("保留整理历史" in m for m in logger.messages("warning")))
        self.assertTrue(any("实际删除记录 1 条" in m for m in logger.messages("info")))
        self.assertEqual(len(self.plugin.get_data("history")), 1)

    def test_none_dest_skipped_with_log(self):
        src = self.root / "src" / "x.mkv"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("video")
        self.transferhis.records.append(
            movie_record(id=3, title="测试剧", type="电视剧", src=str(src), dest=None))
        self.fire_series()
        self.assertTrue(any("缺少转移路径" in m for m in logger.messages("warning")))
        self.assertFalse(src.exists())
        self.assertEqual(self.transferhis.deleted_ids, [3])


class UppercaseExtensionTests(unittest.TestCase):
    """M7：.MKV 大写扩展名与 .mkv 同等处理。"""

    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "keep.txt").write_text("keep")
        self.plugin = make_plugin(del_source=True)
        self.transferhis = FakeTransferHistoryOper()
        self.plugin._transferhis = self.transferhis
        self.plugin._deleter._transferhis = self.transferhis

    def test_uppercase_media_file_deleted(self):
        src = self.root / "src" / "Movie.MKV"
        src.parent.mkdir(parents=True)
        src.write_text("video")
        self.transferhis.records.append(movie_record(id=4, src=str(src)))
        self.plugin.sync_del_by_webhook(webhook_event())
        self.assertFalse(src.exists())
        self.assertEqual(self.transferhis.deleted_ids, [4])


class AutoDisableTests(unittest.TestCase):
    """M6：item_isvirtual 无法识别自动停用——进程内立即生效且不丢配置键。"""

    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()

    def test_disable_preserves_config_and_takes_effect_in_process(self):
        plugin = make_plugin(sync_type="plugin")
        # 模拟用户已保存的全量配置（含挂起的清空历史请求）
        plugin.update_config({
            "enabled": True, "sync_type": "plugin", "notify": True,
            "del_source": True, "del_history": True,
            "exclude_path": "/x", "library_path": "/a:/b",
        })
        event = WebhookEventInfo(
            event="media_del", item_type="Movie", item_name="测试",
            item_path="/x/a.mkv", item_isvirtual=None,
        )
        plugin.sync_del_by_plugin(FakeEvent(event_data=event))
        # 进程内状态与持久化配置都已停用，且配置键完整保留
        self.assertFalse(plugin._enabled)
        self.assertFalse(plugin.get_state())
        self.assertFalse(plugin._stored_config["enabled"])
        self.assertTrue(plugin._stored_config["del_history"])
        self.assertEqual(plugin._stored_config["library_path"], "/a:/b")
        # 后续事件不再进入删除逻辑
        logger.clear()
        event2 = WebhookEventInfo(
            event="media_del", item_type="Movie", item_name="测试",
            item_path="/x/a.mkv", item_isvirtual="False",
        )
        plugin.sync_del_by_plugin(FakeEvent(event_data=event2))
        self.assertEqual(logger.records, [])


class ExcludePathBoundaryTests(unittest.TestCase):
    """M8：排除路径按路径边界匹配，配置侧兼容 Windows 反斜杠。"""

    def test_prefix_without_boundary_not_matched(self):
        self.assertFalse(payloads.is_excluded_path("/mnt/abc/x.mkv", "/mnt/a"))
        self.assertFalse(payloads.is_excluded_path("/mnt/abc/x.mkv", "/mnt/ab"))

    def test_exact_and_child_matched(self):
        self.assertTrue(payloads.is_excluded_path("/mnt/a", "/mnt/a"))
        self.assertTrue(payloads.is_excluded_path("/mnt/a/x.mkv", "/mnt/a"))
        self.assertTrue(payloads.is_excluded_path("/mnt/a/x.mkv", "/mnt/a/"))

    def test_windows_style_exclusion(self):
        self.assertTrue(payloads.is_excluded_path("D:/media/x.mkv", "D:\\media"))
        self.assertTrue(payloads.is_excluded_path("D:\\media\\x.mkv", "D:\\media"))


class PathMappingBoundaryTests(unittest.TestCase):
    """M9：路径映射仅前缀命中替换一次、命中即停不级联、兼容 Windows 盘符行。"""

    def test_non_prefix_occurrence_not_replaced(self):
        self.assertEqual(
            payloads.apply_path_mapping("/shows/data42/x.mkv", "/data:/mnt/link"),
            "/shows/data42/x.mkv")

    def test_prefix_replaced_exactly_once(self):
        # 旧实现全局 replace，会把路径中间与结果里再次出现的映射源一并替换
        self.assertEqual(
            payloads.apply_path_mapping("/data/shows/data42/x.mkv", "/data:/mnt/link"),
            "/mnt/link/shows/data42/x.mkv")

    def test_no_cascade_across_lines(self):
        self.assertEqual(
            payloads.apply_path_mapping("/a/x.mkv", "/a:/b\n/b:/c"),
            "/b/x.mkv")

    def test_windows_drive_line_parsed(self):
        self.assertEqual(
            payloads.apply_path_mapping("D:/media/x.mkv", "D:\\media:/mnt/media"),
            "/mnt/media/x.mkv")

    def test_prefix_boundary_required(self):
        self.assertEqual(
            payloads.apply_path_mapping("/database/x.mkv", "/data:/mnt"),
            "/database/x.mkv")


class NotifyCountTests(unittest.TestCase):
    """L4：通知统计实际删除数；0 条实际删除时不发成功通知。"""

    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()
        self.plugin = make_plugin(notify=True)
        self.transferhis = FakeTransferHistoryOper()
        self.plugin._transferhis = self.transferhis
        self.plugin._deleter._transferhis = self.transferhis

    def test_no_actual_deletion_no_success_notify(self):
        self.transferhis.records.append(movie_record(id=1, title="别的标题"))
        self.plugin.sync_del_by_webhook(webhook_event())
        self.assertEqual(self.transferhis.deleted_ids, [])
        self.assertEqual(self.plugin.messages, [])
        self.assertTrue(any("无实际删除记录" in m for m in logger.messages("info")))

    def test_notify_counts_actual_deletions(self):
        self.transferhis.records.extend([
            movie_record(id=1, title="别的标题"),
            movie_record(id=2),
        ])
        self.plugin.sync_del_by_webhook(webhook_event())
        self.assertEqual(self.transferhis.deleted_ids, [2])
        self.assertEqual(len(self.plugin.messages), 1)
        self.assertIn("删除记录1个", self.plugin.messages[0].get("text", ""))


class HistoryPersistenceTests(unittest.TestCase):
    """L1：历史落盘读-改-写加锁，条数裁剪到上限 500。"""

    def setUp(self):
        logger.clear()
        eventmanager.sent_events.clear()

    def test_history_trimmed_to_max(self):
        plugin = make_plugin()
        transferhis = FakeTransferHistoryOper(records=[movie_record(id=7)])
        plugin._transferhis = transferhis
        plugin._deleter._transferhis = transferhis
        plugin.save_data("history", [{"title": f"旧记录{i}", "unique": f"u{i}"}
                                     for i in range(500)])
        plugin.sync_del_by_webhook(webhook_event())
        history = plugin.get_data("history")
        self.assertEqual(len(history), 500)
        self.assertEqual(history[0]["unique"], "u1")
        self.assertEqual(history[-1]["title"], "测试电影")

    def test_concurrent_saves_no_lost_entries(self):
        plugin = make_plugin()
        deleter = plugin._deleter

        def save_one(index):
            request = payloads.DeleteRequest(media_type="Movie", media_name=f"片{index}")
            deleter._save_history(request=request, media_type=MediaType.MOVIE,
                                  media_source=None, media_id=None,
                                  media_path="/x", year=None, image="img")

        threads = [threading.Thread(target=save_one, args=(i,)) for i in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        history = plugin.get_data("history")
        self.assertEqual(len(history), 20)
        self.assertEqual(len({h["unique"] for h in history}), 20)


if __name__ == "__main__":
    unittest.main()
