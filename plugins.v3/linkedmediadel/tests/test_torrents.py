"""torrents 模块单元测试：锁定潜伏 bug 修复后的行为。"""

import types
import unittest

from tests.stubs import FakeChain, FakeDownloadHistoryOper, load_plugin_module, logger

plugin_module = load_plugin_module()
TorrentCleaner = plugin_module.TorrentCleaner


def download_file(**kwargs):
    record = types.SimpleNamespace(id=None, download_hash=None, state="0", downloader="qb",
                                   fullpath=None)
    record.__dict__.update(kwargs)
    return record


class FakeDataStore:
    def __init__(self):
        self.store = {}

    def get_data(self, key=None, plugin_id=None):
        return self.store.get((plugin_id, key))

    def save_data(self, key, value, plugin_id=None):
        self.store[(plugin_id, key)] = value

    def del_data(self, key=None, plugin_id=None):
        self.store.pop((plugin_id, key), None)


def make_cleaner(files=None, data_store=None):
    return TorrentCleaner(
        chain=FakeChain(),
        downloadhis=FakeDownloadHistoryOper(files=files),
        data_store=data_store or FakeDataStore(),
        default_downloader="qb",
    )


class HandleReturnTypeTests(unittest.TestCase):
    """M5：种子无文件记录（已被外部手动删除）视为成功，让整理历史可正常清除。"""

    def setUp(self):
        logger.clear()

    def test_no_download_files_treated_as_success(self):
        cleaner = make_cleaner(files=[])
        delete_flag, success, hashs = cleaner.handle(media_kind="电影", src="/x/a.mkv",
                                                     torrent_hash="abc")
        self.assertTrue(delete_flag)
        self.assertTrue(success)
        self.assertEqual(hashs, [])
        self.assertTrue(any("视为处理成功" in m for m in logger.messages("info")))

    def test_delete_flag_flow_returns_list(self):
        files = [download_file(download_hash="abc", state="0")]
        cleaner = make_cleaner(files=files)
        delete_flag, success, hashs = cleaner.handle(media_kind="电影", src="/x/a.mkv",
                                                     torrent_hash="abc")
        self.assertTrue(delete_flag)
        self.assertTrue(success)
        self.assertEqual(hashs, ["abc"])


class DelSeedTests(unittest.TestCase):
    """修复：辅种记录缺字段时跳过该条继续处理，不再裸 return None。"""

    def setUp(self):
        logger.clear()

    def test_malformed_record_returns_list(self):
        store = FakeDataStore()
        store.save_data(key="abc", plugin_id="IYUUAutoSeed", value=[{"downloader": None}])
        cleaner = make_cleaner(data_store=store)
        result = cleaner._del_seed(download_id="abc", delete_flag=True, handle_torrent_hashs=["abc"])
        self.assertEqual(result, ["abc"])

    def test_seed_chain_processed(self):
        store = FakeDataStore()
        store.save_data(key="abc", plugin_id="IYUUAutoSeed",
                        value=[{"downloader": "qb", "torrents": ["seed1"]}])
        cleaner = make_cleaner(data_store=store)
        result = cleaner._del_seed(download_id="abc", delete_flag=True, handle_torrent_hashs=[])
        self.assertIn("seed1", result)

    def test_cyclic_seed_records_no_recursion_error(self):
        """L6：A 辅 B、B 辅 A 的循环引用不得导致 RecursionError。"""
        store = FakeDataStore()
        store.save_data(key="A", plugin_id="IYUUAutoSeed",
                        value=[{"downloader": "qb", "torrents": ["B"]}])
        store.save_data(key="B", plugin_id="IYUUAutoSeed",
                        value=[{"downloader": "qb", "torrents": ["A"]}])
        cleaner = make_cleaner(data_store=store)
        result = cleaner._del_seed(download_id="A", delete_flag=True, handle_torrent_hashs=[])
        self.assertIn("A", result)
        self.assertIn("B", result)
        self.assertTrue(any("循环引用" in m for m in logger.messages("info")))


class TorrentTransferTests(unittest.TestCase):
    """M4：删除转种后任务必须使用转种记录的目标任务 id（hash 跨站会变化）。"""

    def setUp(self):
        logger.clear()

    def test_remove_transferred_torrent_uses_target_id(self):
        store = FakeDataStore()
        store.save_data(key="qb-hash_src", plugin_id="TorrentTransfer",
                        value={"to_download": "tr", "to_download_id": "hash_dst",
                               "delete_source": True})
        files = [download_file(download_hash="hash_src", state="0")]
        cleaner = make_cleaner(files=files, data_store=store)
        delete_flag, success, hashs = cleaner.handle(media_kind="电影", src="/x/a.mkv",
                                                     torrent_hash="hash_src")
        self.assertTrue(delete_flag)
        self.assertTrue(success)
        removed = cleaner._chain.removed_torrents
        self.assertTrue(
            any(kw.get("hashs") == "hash_dst" and kw.get("downloader") == "tr" for _, kw in removed),
            f"应以目标 id 删除转种后任务，实际调用：{removed}")
        self.assertFalse(
            any(kw.get("hashs") == "hash_src" and kw.get("downloader") == "tr" for _, kw in removed),
            f"不得用源 hash 删转种后任务，实际调用：{removed}")
        self.assertIn("hash_dst", hashs)


class DelCollectionTests(unittest.TestCase):
    """修复：合集处理异常走 logger.error，不再 print。"""

    def test_exception_logged_not_printed(self):
        class BrokenOper:
            def get_files_by_fullpath(self, fullpath):
                raise RuntimeError("模拟故障")

        cleaner = TorrentCleaner(chain=FakeChain(), downloadhis=BrokenOper(),
                                 data_store=FakeDataStore(), default_downloader="qb")
        result = cleaner._del_collection(src="/x", delete_flag=True, torrent_hash="abc",
                                         download_files=[], handle_torrent_hashs=[])
        self.assertEqual(result, [])
        self.assertTrue(any("合集失败" in m for m in logger.messages("error")))


if __name__ == "__main__":
    unittest.main()
