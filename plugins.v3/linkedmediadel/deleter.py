"""删除执行核心：转移记录、源文件、下载任务的同步清理，以及通知与历史落盘。"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from app.schemas.types import EventType, MediaImageType, MediaSource, MediaType, MessageType
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.media import build_media_key, resolve_media_identity
from app.sdk.utilities import SystemUtils

from .payloads import DeleteRequest, apply_path_mapping, as_media_type, is_excluded_path, library_mapping_dests
from .transfer_query import query_transfer_history

# 默认通知图（媒体身份缺失时的兜底）
DEFAULT_NOTIFY_IMAGE = "https://emby.media/notificationicon.png"

# 插件历史落盘的读-改-写锁（事件经线程池并发执行）与条数上限
_HISTORY_LOCK = threading.Lock()
_HISTORY_MAX = 500


class SyncDeleter:
    """同步删除执行器，依赖显式注入。

    :param transferhis: TransferHistoryOper 实例
    :param torrents: TorrentCleaner 实例
    :param chain: 插件链路口子（obtain_specific_image 等）
    :param eventmanager: 事件总线（排除路径时外发 networkdisk_del）
    :param data_store: 插件数据读写口子（get_data/save_data），即插件实例
    :param post_message: 通知发送回调
    """

    def __init__(self, *, transferhis, torrents, chain, eventmanager, data_store, post_message,
                 del_source: bool, notify: bool, library_path: str, exclude_path: str):
        self._transferhis = transferhis
        self._torrents = torrents
        self._chain = chain
        self._eventmanager = eventmanager
        self._data_store = data_store
        self._post_message = post_message
        self._del_source = del_source
        self._notify = notify
        self._library_path = library_path
        self._exclude_path = exclude_path

    def handle_exclusion(self, request: DeleteRequest) -> bool:
        """命中排除路径时不删除本地数据，改为通知网盘删除插件删除网盘资源。"""
        if not is_excluded_path(request.media_path, self._exclude_path):
            return False
        logger.info(f"媒体路径 {request.media_path} 已被排除，暂不处理")
        self._eventmanager.send_event(EventType.PluginAction, {
            "action": "networkdisk_del",
            "media_path": request.media_path,
            "media_name": request.media_name,
            "media_source": request.media_source.value if request.media_source else None,
            "media_id": request.media_id,
            "media_type": request.media_type,
            "season_num": request.season_num,
            "episode_num": request.episode_num,
        })
        return True

    def execute(self, request: DeleteRequest) -> None:
        """执行同步删除：转移历史 → 源文件/种子 → 通知与历史落盘。"""
        if not request.media_type or not request.media_name:
            logger.error(f"{request.media_name} 同步删除失败，未获取到媒体类型，请检查媒体是否刮削")
            return

        media_source, media_id = resolve_media_identity(
            media_source=request.media_source,
            media_id=request.media_id,
        )
        media_path = apply_path_mapping(request.media_path, self._library_path)

        # 兼容重新整理的场景
        if media_path and Path(media_path).exists():
            logger.warning(f"转移路径 {media_path} 未被删除或重新生成，跳过处理")
            return

        # 查询转移记录
        msg, transfer_history = query_transfer_history(
            self._transferhis,
            media_type=request.media_type,
            media_name=request.media_name,
            media_path=media_path,
            media_source=media_source,
            media_id=media_id,
            season_num=request.season_num,
            episode_num=request.episode_num,
        )

        if not transfer_history:
            logger.warning(
                f"{request.media_type} {request.media_name} 未获取到可删除数据，请检查路径映射或媒体身份是否正确")
            return

        if request.delete_time:
            latest_his = max(transfer_history, key=lambda x: x.date)
            if request.delete_time < latest_his.date:
                logger.warning(f"忽略删除 {msg}, 整理时间: {latest_his.date}, 发生在删除事件: {request.delete_time} 之后")
                return

        logger.info(f"开始同步删除 {msg}, 获取到 {len(transfer_history)} 条转移记录")
        # 开始删除
        year = None
        del_cnt = 0
        del_torrent_hashs = []
        stop_torrent_hashs = []
        error_cnt = 0
        image = DEFAULT_NOTIFY_IMAGE
        for transferhis in transfer_history:
            title = transferhis.title
            if not title or title not in request.media_name:
                logger.warning(
                    f"当前转移记录 {transferhis.id} {title} {transferhis.media_source}:{transferhis.media_id} "
                    f"与删除媒体{request.media_name}不符，防误删，暂不自动删除")
                continue
            image = transferhis.image or image
            year = transferhis.year
            history_delete_ready = True

            # 删除种子任务
            if self._del_source:
                try:
                    # 1、直接删除源文件
                    if transferhis.src and Path(transferhis.src).suffix.lower() in settings.RMT_MEDIAEXT:
                        # 删除硬链接文件和源文件
                        if transferhis.dest:
                            if Path(transferhis.dest).exists():
                                Path(transferhis.dest).unlink(missing_ok=True)
                                self._remove_parent_dir(Path(transferhis.dest))
                        else:
                            logger.warning(f"转移记录 {transferhis.id} 缺少转移路径，跳过目标文件删除")
                        if Path(transferhis.src).exists():
                            logger.info(f"源文件 {transferhis.src} 开始删除")
                            Path(transferhis.src).unlink(missing_ok=True)
                            logger.info(f"源文件 {transferhis.src} 已删除")
                            self._remove_parent_dir(Path(transferhis.src))

                        if transferhis.download_hash:
                            try:
                                # 2、判断种子是否被删除完
                                delete_flag, success_flag, handle_torrent_hashs = self._torrents.handle(
                                    media_kind=transferhis.type,
                                    src=transferhis.src,
                                    torrent_hash=transferhis.download_hash)
                                if not success_flag:
                                    error_cnt += 1
                                    history_delete_ready = False
                                else:
                                    if delete_flag:
                                        del_torrent_hashs += handle_torrent_hashs
                                    else:
                                        stop_torrent_hashs += handle_torrent_hashs
                            except Exception as e:
                                error_cnt += 1
                                history_delete_ready = False
                                logger.error("删除种子失败：%s" % str(e))
                except Exception as e:
                    # 单条记录清理失败不影响后续记录，保留该条整理历史供重试
                    error_cnt += 1
                    history_delete_ready = False
                    logger.error(f"删除媒体文件失败（转移记录 {transferhis.id}）：{str(e)}")

            # 整理历史是跨文件系统和下载器清理失败后的重试依据，只能最后删除。
            if history_delete_ready:
                self._transferhis.delete(transferhis.id)
                del_cnt += 1
            else:
                logger.warning(f"外部清理未完成，保留整理历史：{transferhis.id}")

        logger.info(f"同步删除 {msg} 完成！实际删除记录 {del_cnt} 条")

        media_type = as_media_type(request.media_type)

        # 发送消息
        if self._notify:
            if del_cnt > 0:
                self._send_notify(msg=msg, media_type=media_type, media_source=media_source,
                                  media_id=media_id, season_num=request.season_num,
                                  episode_num=request.episode_num, image=image,
                                  transfer_count=del_cnt,
                                  del_torrent_hashs=del_torrent_hashs,
                                  stop_torrent_hashs=stop_torrent_hashs, error_cnt=error_cnt)
            else:
                logger.info(f"{msg} 无实际删除记录，跳过成功通知")

        self._save_history(request=request, media_type=media_type, media_source=media_source,
                           media_id=media_id, media_path=media_path, year=year, image=image)

    def _send_notify(self, *, msg, media_type, media_source, media_id, season_num, episode_num,
                     image, transfer_count, del_torrent_hashs, stop_torrent_hashs, error_cnt):
        """发送同步删除完成通知。"""
        backrop_image = image
        if media_source == MediaSource.TMDB and media_id:
            backrop_image = self._chain.obtain_specific_image(
                mediaid=media_id,
                mtype=media_type,
                image_type=MediaImageType.Backdrop,
                season=season_num,
                episode=episode_num
            ) or image

        torrent_cnt_msg = ""
        if del_torrent_hashs:
            torrent_cnt_msg += f"删除种子{len(set(del_torrent_hashs))}个\n"
        if stop_torrent_hashs:
            stop_cnt = 0
            # 排除已删除
            for stop_hash in set(stop_torrent_hashs):
                if stop_hash not in set(del_torrent_hashs):
                    stop_cnt += 1
            if stop_cnt > 0:
                torrent_cnt_msg += f"暂停种子{stop_cnt}个\n"
        if error_cnt:
            torrent_cnt_msg += f"删种失败{error_cnt}个\n"
        # 发送通知
        self._post_message(
            mtype=MessageType.Plugin,
            title="媒体库同步删除任务完成",
            image=backrop_image,
            text=f"{msg}\n"
                 f"删除记录{transfer_count}个\n"
                 f"{torrent_cnt_msg}"
                 f"时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}"
        )

    def _save_history(self, *, request, media_type, media_source, media_id, media_path, year, image):
        """读取并追加插件历史记录（读-改-写加锁，事件在线程池中并发执行）。"""
        with _HISTORY_LOCK:
            history = self._data_store.get_data("history") or []

            # 获取poster
            poster_image = image
            if media_source == MediaSource.TMDB and media_id:
                poster_image = self._chain.obtain_specific_image(
                    mediaid=media_id,
                    mtype=media_type,
                    image_type=MediaImageType.Poster,
                ) or image
            now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
            season_num = request.season_num
            episode_num = request.episode_num
            history.append({
                "type": media_type.value,
                "title": request.media_name,
                "year": year,
                "path": media_path,
                "media_source": media_source.value if media_source else None,
                "media_id": media_id,
                "season": season_num if season_num and str(season_num).isdigit() else None,
                "episode": episode_num if episode_num and str(episode_num).isdigit() else None,
                "image": poster_image,
                "del_time": now,
                "unique": f"{request.media_name}:{build_media_key(media_source, media_id) or 'unknown'}:{now}"
            })
            # 只保留最近若干条，防止无限增长
            if len(history) > _HISTORY_MAX:
                history = history[-_HISTORY_MAX:]

            # 保存历史
            self._data_store.save_data("history", history)

    def _remove_parent_dir(self, file_path: Path):
        """回收空目录：父路径下无媒体文件时逐级上溯（最多三级），仅删除真正为空的目录。

        安全边界：os.rmdir 对非空目录天然失败即停（目录内有 nfo/字幕等非媒体文件时不会误删）；
        上溯遇到路径映射目标根、挂载点或文件系统根即停，每步停止原因记 debug 日志。
        """
        if SystemUtils.exits_files(file_path.parent, settings.RMT_MEDIAEXT):
            logger.debug(f"目录 {file_path.parent} 下仍存在媒体文件，不回收空目录")
            return
        stop_roots = set(library_mapping_dests(self._library_path))
        current = file_path.parent
        for _ in range(3):
            current_text = str(current).replace("\\", "/").rstrip("/")
            if not current_text or current.parent == current:
                logger.debug(f"已到文件系统根，停止回收空目录")
                break
            if current_text in stop_roots:
                logger.debug(f"目录 {current_text} 为路径映射目标根，停止回收空目录")
                break
            if os.path.ismount(current):
                logger.debug(f"目录 {current_text} 为挂载点，停止回收空目录")
                break
            try:
                os.rmdir(current)
            except OSError as e:
                logger.debug(f"目录 {current_text} 非空或不可删除（{e}），停止回收空目录")
                break
            logger.warning(f"本地空目录 {current_text} 已删除")
            current = current.parent
        else:
            logger.debug(f"已达到最大上溯层级，停止回收空目录")
