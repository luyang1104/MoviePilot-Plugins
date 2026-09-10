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
    """修复：错误路径必须返回 (False, False, [])，不再是 (False, False, 0)。"""

    def setUp(self):
        logger.clear()

    def test_no_download_files_returns_list(self):
        cleaner = make_cleaner(files=[])
        delete_flag, success, hashs = cleaner.handle(media_kind="电影", src="/x/a.mkv",
                                                     torrent_hash="abc")
        self.assertFalse(delete_flag)
        self.assertFalse(success)
        self.assertEqual(hashs, [])

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
