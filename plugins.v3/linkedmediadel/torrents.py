"""下载器侧清理：种子局部删除则暂停、全部删除则删种，并联动处理转种、辅种与合集。"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from app.sdk.logging import logger


class TorrentCleaner:
    """封装种子处理三件套，依赖显式注入，便于测试与复用。

    :param chain: 插件链路口子（remove_torrents / stop_torrents）
    :param downloadhis: DownloadHistoryOper 实例
    :param data_store: 跨插件数据读写口子（get_data/del_data(key=..., plugin_id=...)），即插件实例
    :param default_downloader: 默认下载器名称
    """

    def __init__(self, *, chain, downloadhis, data_store, default_downloader: Optional[str] = None):
        self._chain = chain
        self._downloadhis = downloadhis
        self._data_store = data_store
        self._default_downloader = default_downloader

    def handle(self, media_kind: str, src: str, torrent_hash: str) -> Tuple[bool, bool, List[str]]:
        """判断种子是否局部删除。

        :return: (是否全部删除, 是否处理成功, 已处理的种子hash列表)
        """
        download_id = torrent_hash
        download = self._default_downloader
        history_key = "%s-%s" % (download, torrent_hash)
        plugin_id = "TorrentTransfer"
        transfer_history = self._data_store.get_data(key=history_key, plugin_id=plugin_id)
        logger.info(f"查询到 {history_key} 转种历史 {transfer_history}")

        handle_torrent_hashs = []
        try:
            # 删除本次种子记录
            self._downloadhis.delete_file_by_fullpath(fullpath=src)

            # 根据种子hash查询所有下载器文件记录
            download_files = self._downloadhis.get_files_by_hash(download_hash=torrent_hash)
            if not download_files:
                # 无文件记录说明种子已被外部手动清理干净，视为成功让整理历史可以正常清除；
                # 与「真失败」区分，避免每次重试同样失败导致历史残留
                logger.info(
                    f"未查询到种子任务 {torrent_hash} 的文件记录，该种子应已被外部删除，视为处理成功")
                return True, True, []

            # 查询未删除数
            no_del_cnt = 0
            for download_file in download_files:
                if download_file and download_file.state and int(download_file.state) == 1:
                    no_del_cnt += 1

            if no_del_cnt > 0:
                logger.info(
                    f"查询种子任务 {torrent_hash} 存在 {no_del_cnt} 个未删除文件，执行暂停种子操作")
                delete_flag = False
            else:
                logger.info(
                    f"查询种子任务 {torrent_hash} 文件已全部删除，执行删除种子操作")
                delete_flag = True

            # 如果有转种记录，则删除转种后的下载任务
            if transfer_history and isinstance(transfer_history, dict):
                download = transfer_history["to_download"]
                download_id = transfer_history["to_download_id"]
                delete_source = transfer_history["delete_source"]

                # 删除种子
                if delete_flag:
                    # 删除转种记录
                    self._data_store.del_data(key=history_key, plugin_id=plugin_id)

                    # 转种后未删除源种时，同步删除源种
                    if not delete_source:
                        logger.info(f"{history_key} 转种时未删除源下载任务，开始删除源下载任务…")

                        # 删除源种子
                        logger.info(f"删除源下载器下载任务：{self._default_downloader} - {torrent_hash}")
                        self._chain.remove_torrents(torrent_hash)
                        handle_torrent_hashs.append(torrent_hash)

                    # 删除转种后任务（使用转种记录的目标任务 id，hash 跨站可能已变化）
                    logger.info(f"删除转种后下载任务：{download} - {download_id}")
                    self._chain.remove_torrents(hashs=download_id, downloader=download)
                    handle_torrent_hashs.append(download_id)
                else:
                    # 暂停种子
                    # 转种后未删除源种时，同步暂停源种
                    if not delete_source:
                        logger.info(f"{history_key} 转种时未删除源下载任务，开始暂停源下载任务…")

                        # 暂停源种子
                        logger.info(f"暂停源下载器下载任务：{self._default_downloader} - {torrent_hash}")
                        self._chain.stop_torrents(torrent_hash)
                        handle_torrent_hashs.append(torrent_hash)

                    logger.info(f"暂停转种后下载任务：{download} - {download_id}")
                    self._chain.stop_torrents(hashs=download_id, downloader=download)
                    handle_torrent_hashs.append(download_id)
            else:
                # 未转种的情况
                if delete_flag:
                    # 删除源种子
                    logger.info(f"删除源下载器下载任务：{download} - {download_id}")
                    self._chain.remove_torrents(download_id)
                else:
                    # 暂停源种子
                    logger.info(f"暂停源下载器下载任务：{download} - {download_id}")
                    self._chain.stop_torrents(download_id)
                handle_torrent_hashs.append(download_id)

            # 处理辅种
            handle_torrent_hashs = self._del_seed(download_id=download_id,
                                                  delete_flag=delete_flag,
                                                  handle_torrent_hashs=handle_torrent_hashs)
            # 处理合集
            if str(media_kind) == "电视剧":
                handle_torrent_hashs = self._del_collection(src=src,
                                                            delete_flag=delete_flag,
                                                            torrent_hash=torrent_hash,
                                                            download_files=download_files,
                                                            handle_torrent_hashs=handle_torrent_hashs)
            return delete_flag, True, handle_torrent_hashs
        except Exception as e:
            logger.error(f"删种失败： {str(e)}")
            return False, False, []

    def _del_seed(self, download_id, delete_flag, handle_torrent_hashs, visited=None):
        """删除/暂停辅种（联动 IYUUAutoSeed 记录）；visited 防止辅种互相引用时无限递归。"""
        if visited is None:
            visited = set()
        if download_id in visited:
            logger.info(f"辅种 {download_id} 已处理过（辅种记录存在循环引用），跳过重复递归")
            return handle_torrent_hashs
        visited.add(download_id)

        # 查询是否有辅种记录
        history_key = download_id
        plugin_id = "IYUUAutoSeed"
        seed_history = self._data_store.get_data(key=history_key, plugin_id=plugin_id) or []
        logger.info(f"查询到 {history_key} 辅种历史 {seed_history}")

        # 有辅种记录则处理辅种
        if seed_history and isinstance(seed_history, list):
            for history in seed_history:
                downloader = history.get("downloader")
                torrents = history.get("torrents")
                if not downloader or not torrents:
                    continue
                if not isinstance(torrents, list):
                    torrents = [torrents]

                # 删除辅种历史
                for torrent in torrents:
                    handle_torrent_hashs.append(torrent)
                    # 删除辅种
                    if delete_flag:
                        logger.info(f"删除辅种：{downloader} - {torrent}")
                        self._chain.remove_torrents(hashs=torrent, downloader=downloader)
                    # 暂停辅种
                    else:
                        self._chain.stop_torrents(hashs=torrent, downloader=downloader)
                        logger.info(f"辅种：{downloader} - {torrent} 暂停")

                    # 处理辅种的辅种
                    handle_torrent_hashs = self._del_seed(download_id=torrent,
                                                          delete_flag=delete_flag,
                                                          handle_torrent_hashs=handle_torrent_hashs,
                                                          visited=visited)

            # 删除辅种历史
            if delete_flag:
                self._data_store.del_data(key=history_key, plugin_id=plugin_id)
        return handle_torrent_hashs

    def _del_collection(self, src: str, delete_flag: bool, torrent_hash: str, download_files: list,
                        handle_torrent_hashs: list):
        """处理合集种子。"""
        try:
            src_download_files = self._downloadhis.get_files_by_fullpath(fullpath=src)
            if src_download_files:
                for download_file in src_download_files:
                    # src查询记录 判断download_hash是否不一致
                    if download_file and download_file.download_hash and str(download_file.download_hash) != str(
                            torrent_hash):
                        # 查询新download_hash对应files数量
                        hash_download_files = self._downloadhis.get_files_by_hash(
                            download_hash=download_file.download_hash)
                        # 新download_hash对应files数量 > 删种download_hash对应files数量 = 合集种子
                        if hash_download_files \
                                and len(hash_download_files) > len(download_files) \
                                and hash_download_files[0].id > download_files[-1].id:
                            # 查询未删除数
                            no_del_cnt = 0
                            for hash_download_file in hash_download_files:
                                if hash_download_file and hash_download_file.state and int(
                                        hash_download_file.state) == 1:
                                    no_del_cnt += 1
                            if no_del_cnt > 0:
                                logger.info(f"合集种子 {download_file.download_hash} 文件未完全删除，执行暂停种子操作")
                                delete_flag = False

                            # 删除合集种子
                            if delete_flag:
                                self._chain.remove_torrents(hashs=download_file.download_hash,
                                                            downloader=download_file.downloader)
                                logger.info(f"删除合集种子 {download_file.downloader} {download_file.download_hash}")
                            else:
                                # 暂停合集种子
                                self._chain.stop_torrents(hashs=download_file.download_hash,
                                                          downloader=download_file.downloader)
                                logger.info(f"暂停合集种子 {download_file.downloader} {download_file.download_hash}")
                            # 已处理种子+1
                            handle_torrent_hashs.append(download_file.download_hash)

                            # 处理合集辅种
                            handle_torrent_hashs = self._del_seed(download_id=download_file.download_hash,
                                                                  delete_flag=delete_flag,
                                                                  handle_torrent_hashs=handle_torrent_hashs)
        except Exception as e:
            logger.error(f"处理 {torrent_hash} 合集失败：{str(e)}")

        return handle_torrent_hashs
