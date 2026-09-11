"""转移历史查询：按媒体身份与季/集粒度组装 TransferHistoryOper 查询。"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from app.schemas.types import MediaSource, MediaType
from app.sdk.logging import logger
from app.sdk.media import build_media_key

from .payloads import as_media_type


def query_transfer_history(
    transferhis,
    *,
    media_type: str,
    media_name: str,
    media_path: str,
    media_source: Optional[MediaSource],
    media_id: Optional[str],
    season_num: Optional[str],
    episode_num: Optional[str],
) -> Tuple[str, List[Any]]:
    """查询转移记录，返回（描述消息, 记录列表）；参数非法或身份缺失时返回空列表。"""
    season_present = season_num is not None and str(season_num) != ""
    episode_present = episode_num is not None and str(episode_num) != ""
    # Emby 原生 webhook 删除整季（Season 项）时季号在 IndexNumber，MP 核心赋出
    # season_id=None、episode_id=<季号>，兜底把集编号还原为季编号
    if str(media_type) == "Season" and not season_present and episode_present and str(episode_num).isdigit():
        logger.info(f"{media_name} 整季删除的季号位于集编号字段（{episode_num}），按第 {episode_num} 季处理")
        season_num, episode_num = episode_num, None
        season_present, episode_present = True, False

    # 季数（特别篇 season 为 int 0，不能用真值判断，否则退化为整剧删除）
    if season_present:
        if not str(season_num).isdigit():
            logger.error(f"{media_name} 同步删除失败，季编号格式无效")
            return "", []
        season_num = str(season_num).rjust(2, "0")
    # 集数
    if episode_present:
        if not str(episode_num).isdigit() or not season_present:
            logger.error(f"{media_name} 同步删除失败，集编号格式无效或缺少季编号")
            return "", []
        episode_num = str(episode_num).rjust(2, "0")

    # 类型
    mtype = as_media_type(media_type)
    identity_text = build_media_key(media_source, media_id) or "未识别媒体"

    # 删除电影
    if mtype == MediaType.MOVIE:
        msg = f"电影 {media_name} {identity_text}"
        if not media_source or not media_id:
            return msg, []
        if not media_path:
            # 真实 TransferHistory.list_by 对空 dest 跳过路径过滤，会命中该媒体全部版本，必须拒绝
            logger.warning(f"电影 {media_name} 缺少转移路径，无法精确匹配版本，拒绝执行同步删除")
            return msg, []
        transfer_history = transferhis.get_by(
            media_source=media_source,
            media_id=media_id,
            mtype=mtype.value,
            dest=media_path,
        )
    # 删除电视剧
    elif mtype == MediaType.TV and not season_num and not episode_num:
        msg = f"剧集 {media_name} {identity_text}"
        if not media_source or not media_id:
            return msg, []
        transfer_history = transferhis.get_by(
            media_source=media_source,
            media_id=media_id,
            mtype=mtype.value,
        )
    # 删除季 S02
    elif mtype == MediaType.TV and season_num and not episode_num:
        msg = f"剧集 {media_name} S{season_num} {identity_text}"
        if not media_source or not media_id:
            return msg, []
        transfer_history = transferhis.get_by(
            media_source=media_source,
            media_id=media_id,
            mtype=mtype.value,
            season=f"S{season_num}",
        )
    # 删除剧集S02E02
    elif mtype == MediaType.TV and season_num and episode_num:
        msg = f"剧集 {media_name} S{season_num}E{episode_num} {identity_text}"
        if not media_source or not media_id:
            return msg, []
        if not media_path:
            # 单集删除必须按 dest 精确匹配，空路径拒绝执行
            logger.warning(f"剧集 {media_name} S{season_num}E{episode_num} 缺少转移路径，无法精确匹配单集，拒绝执行同步删除")
            return msg, []
        transfer_history = transferhis.get_by(
            media_source=media_source,
            media_id=media_id,
            mtype=mtype.value,
            season=f"S{season_num}",
            episode=f"E{episode_num}",
            dest=media_path,
        )
    else:
        return "", []

    return msg, transfer_history
