"""Webhook 负载归一化：把 Emby 原生 Webhook / Scripter X 上报的松散字段整理成统一的删除请求。

历史教训（上游 thsrite/MoviePilot-Plugins issue #359）：Scripter X/Emby webhook 传入的
item_isvirtual 是字符串（如 "False"），MP 核心不做类型强转，隐式真值判断会把所有删除事件
静默跳过。所有布尔语义字段必须经过 normalize_bool，禁止 `if value:` 式判断。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.schemas.types import MediaType
from app.sdk.media import resolve_media_identity
from app.sdk.utilities import StringUtils

_TRUE_WORDS = ("true", "1", "yes", "y", "on")
_FALSE_WORDS = ("false", "0", "no", "n", "off")


def normalize_bool(value: Any) -> Optional[bool]:
    """把 webhook 传入的松散布尔值（字符串/数字/布尔）归一化为 True/False。

    无法识别（None、空串、未知文本）返回 None，调用方必须据此走保护逻辑，不得默认放行删除。
    """
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


def normalize_path(path: Any) -> str:
    """兼容 Windows 路径，如 C:\\test.mp4 转换为 C:/test.mp4。"""
    return str(path or "").replace("\\", "/")


def _normalize_dir_path(path: Any) -> str:
    """目录路径归一化：反斜杠转斜杠并去除尾部斜杠，供前缀边界比较。"""
    return normalize_path(path).strip().rstrip("/")


def is_excluded_path(media_path: str, exclude_path: str) -> bool:
    """命中逗号分隔的排除路径前缀时返回 True（按路径边界比较，/mnt/a 不命中 /mnt/abc）。"""
    if not exclude_path or not media_path:
        return False
    candidate = _normalize_dir_path(media_path)
    return any(
        candidate == item or candidate.startswith(item + "/")
        for item in (_normalize_dir_path(item) for item in exclude_path.split(","))
        if item
    )


def _parse_mapping_lines(library_path: str):
    """解析路径映射配置行，产出 (源, 目标) 归一化对；rsplit 兼容 Windows 盘符行。"""
    for line in str(library_path or "").split("\n"):
        sub_paths = line.rsplit(":", 1)
        if len(sub_paths) < 2:
            continue
        src, dst = _normalize_dir_path(sub_paths[0]), _normalize_dir_path(sub_paths[1])
        if src and dst:
            yield src, dst


def library_mapping_dests(library_path: str) -> list:
    """路径映射的目标根（dst）列表，空目录回收上溯到这些根即停。"""
    return [dst for _, dst in _parse_mapping_lines(library_path)]


def apply_path_mapping(media_path: str, library_path: str) -> str:
    """按「媒体服务器路径:MoviePilot路径」逐行映射（处理同一媒体多分辨率的情况）。

    仅当映射源命中路径前缀（含路径边界）时替换一次并停止，避免路径中间误替换与多行级联。
    """
    if not library_path or not media_path:
        return media_path
    media_path = normalize_path(media_path)
    for src, dst in _parse_mapping_lines(library_path):
        if media_path == src or media_path.startswith(src + "/"):
            return dst + media_path[len(src):]
    return media_path


def as_media_type(media_type: Any) -> MediaType:
    """Webhook 上报的媒体类型字符串归一化为 MediaType（Emby 电影为 Movie/MOV，其余按剧集处理）。"""
    return MediaType.MOVIE if str(media_type) in ("Movie", "MOV") else MediaType.TV


def parse_delete_time(json_object: Any) -> Optional[str]:
    """从 webhook 原始报文取删除操作时间；缺失或解析失败返回 None（跳过时间比较）。"""
    if not isinstance(json_object, dict):
        return None
    raw = json_object.get("UtcTimestamp") or json_object.get("Date")  # jellyfin / emby
    if not raw:
        return None
    timestamp = StringUtils.str_to_timestamp(raw)
    # 真实 StringUtils.str_to_timestamp 解析失败返回 0（不是 None），0 会被格式化成 1970 年
    if not timestamp:
        return None
    return StringUtils.format_timestamp(timestamp)


@dataclass
class DeleteRequest:
    """统一的删除请求：三种事件入口（webhook/scripterx/action）归一化后的产物。"""

    media_type: Optional[str]
    media_name: Optional[str]
    media_path: str = ""
    media_source: Any = None
    media_id: Optional[str] = None
    season_num: Optional[str] = None
    episode_num: Optional[str] = None
    delete_time: Optional[str] = None


def build_webhook_request(event_data) -> DeleteRequest:
    """Emby 原生 Webhook（library.deleted，兼容 Jellyfin ItemDeleted）。"""
    media_source, media_id = resolve_media_identity(event_data)
    return DeleteRequest(
        media_type=event_data.media_type,
        media_name=event_data.item_name,
        media_path=normalize_path(event_data.item_path),
        media_source=media_source,
        media_id=media_id,
        season_num=event_data.season_id,
        episode_num=event_data.episode_id,
        delete_time=parse_delete_time(event_data.json_object),
    )


def build_scripterx_request(event_data) -> DeleteRequest:
    """Scripter X 插件（media_del）。item_isvirtual 由调用方先行处理。"""
    media_source, media_id = resolve_media_identity(event_data)
    return DeleteRequest(
        media_type=event_data.item_type,
        media_name=event_data.item_name,
        media_path=normalize_path(event_data.item_path),
        media_source=media_source,
        media_id=media_id,
        season_num=event_data.season_id,
        episode_num=event_data.episode_id,
    )


def build_action_request(event_data: dict) -> DeleteRequest:
    """PluginAction（media_sync_del）联动请求。"""
    media_source, media_id = resolve_media_identity(media=event_data)
    return DeleteRequest(
        media_type=event_data.get("media_type"),
        media_name=event_data.get("media_name"),
        media_path=normalize_path(event_data.get("media_path")),
        media_source=media_source,
        media_id=media_id,
        season_num=event_data.get("season_num"),
        episode_num=event_data.get("episode_num"),
    )
