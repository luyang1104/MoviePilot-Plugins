"""MoviePilot 运行时桩件：让 LinkedMediaDel 在纯标准库环境下被单元测试加载。

仿照 cloudstrmbutler/tests/stubs.py 的模式：把 `app.*` 导入替换为内存假实现，
再用 importlib 以包形式加载插件目录（相对导入因此可用）。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
import types
from datetime import datetime
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RecordingLogger:
    """记录全部日志调用，供断言跳过分支也有日志输出。"""

    def __init__(self):
        self.records = []

    def _log(self, level, msg, *args, **kwargs):
        if args:
            try:
                msg = msg % args
            except (TypeError, ValueError):
                pass
        self.records.append((level, str(msg)))

    def info(self, msg, *args, **kwargs):
        self._log("info", msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._log("warning", msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._log("error", msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self._log("debug", msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self._log("exception", msg, *args, **kwargs)

    def messages(self, level=None):
        return [m for lv, m in self.records if level is None or lv == level]

    def clear(self):
        self.records.clear()


logger = RecordingLogger()


class MediaType(Enum):
    MOVIE = "电影"
    TV = "电视剧"
    MUSIC = "音乐"
    COLLECTION = "系列"
    UNKNOWN = "未知"


class MediaSource(str, Enum):
    TMDB = "themoviedb"
    Douban = "douban"
    Bangumi = "bangumi"


class MediaImageType(Enum):
    Poster = "poster_path"
    Backdrop = "backdrop_path"


class MessageType(Enum):
    Plugin = "插件"


class EventType:
    WebhookMessage = "WebhookMessage"
    PluginAction = "PluginAction"
    DownloadFileDeleted = "DownloadFileDeleted"


class FakeEvent:
    def __init__(self, event_data=None):
        self.event_data = event_data


class FakeEventManager:
    """register 是透传装饰器；send_event 记录全部外发事件。"""

    def __init__(self):
        self.sent_events = []

    @staticmethod
    def register(event_type):
        return lambda func: func

    def send_event(self, event_type, data=None):
        self.sent_events.append((event_type, data))


eventmanager = FakeEventManager()


class Response:
    def __init__(self, success=True, message=None, data=None):
        self.success = success
        self.message = message
        self.data = data

    def __class_getitem__(cls, item):
        return cls


class WebhookEventInfo:
    """松散的事件载体，字段与 app.schemas.WebhookEventInfo 对齐。"""

    def __init__(self, **kwargs):
        self.event = None
        self.channel = None
        self.server_name = None
        self.item_type = None
        self.item_name = None
        self.item_id = None
        self.item_path = None
        self.season_id = None
        self.episode_id = None
        self.media_source = None
        self.media_id = None
        self.item_isvirtual = None
        self.media_type = None
        self.json_object = {}
        self.__dict__.update(kwargs)


class FakeSettings:
    RMT_MEDIAEXT = [
        ".mp4", ".mkv", ".ts", ".iso", ".rmvb", ".avi", ".mov",
        ".mpeg", ".mpg", ".wmv", ".flv", ".m2ts",
    ]
    TMDB_IMAGE_DOMAIN = "image.tmdb.org"


settings = FakeSettings()


class FakeStringUtils:
    """StringUtils 时间相关方法的最小真实语义实现。"""

    @staticmethod
    def str_to_timestamp(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            # 13 位按毫秒处理
            return value / 1000 if value > 1e12 else float(value)
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return FakeStringUtils.str_to_timestamp(int(text))
        try:
            normalized = text.replace("Z", "+00:00")
            # 兼容 Emby 7 位小数秒
            if "." in normalized:
                head, tail = normalized.split(".", 1)
                frac, _, tz = tail.partition("+")
                normalized = f"{head}.{frac[:6]}+{tz}" if tz else f"{head}.{frac[:6]}"
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return None

    @staticmethod
    def format_timestamp(ts):
        if ts is None:
            return None
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


StringUtils = FakeStringUtils()


class FakeSystemUtils:
    @staticmethod
    def exits_files(path, exts):
        if not path or not os.path.isdir(path):
            return False
        exts = tuple(str(e).lower() for e in exts)
        for _, _, files in os.walk(path):
            if any(f.lower().endswith(exts) for f in files):
                return True
        return False


SystemUtils = FakeSystemUtils()


def build_media_key(media_source, media_id):
    if not media_source or not media_id:
        return None
    source_value = getattr(media_source, "value", media_source)
    return f"{source_value}:{media_id}"


def _coerce_source(value):
    if value is None or isinstance(value, MediaSource):
        return value
    try:
        return MediaSource(str(value))
    except ValueError:
        return value


def resolve_media_identity(*args, media=None, media_source=None, media_id=None):
    """支持插件的三种调用形态：位置参数事件对象、media= 字典/对象、关键字参数。"""
    if args:
        obj = args[0]
        media_source = getattr(obj, "media_source", None)
        media_id = getattr(obj, "media_id", None)
    elif media is not None:
        if isinstance(media, dict):
            media_source = media.get("media_source")
            media_id = media.get("media_id")
        else:
            media_source = getattr(media, "media_source", None)
            media_id = getattr(media, "media_id", None)
    media_source = _coerce_source(media_source)
    if media_id in (None, ""):
        media_id = None
    elif media_id is not None:
        media_id = str(media_id)
    return media_source, media_id


class FakeChain:
    def __init__(self):
        self.removed_torrents = []
        self.stopped_torrents = []
        self.image_requests = []

    def obtain_specific_image(self, **kwargs):
        self.image_requests.append(kwargs)
        return None

    def remove_torrents(self, *args, **kwargs):
        self.removed_torrents.append((args, kwargs))
        return True

    def stop_torrents(self, *args, **kwargs):
        self.stopped_torrents.append((args, kwargs))
        return True


class TransferRecord:
    """转移历史记录，字段与 app.db.models.transferhistory 对齐。"""

    def __init__(self, **kwargs):
        self.id = None
        self.type = None
        self.title = None
        self.year = None
        self.src = None
        self.dest = None
        self.media_source = None
        self.media_id = None
        self.season = None
        self.episode = None
        self.image = None
        self.date = None
        self.download_hash = None
        self.__dict__.update(kwargs)


class FakeTransferHistoryOper:
    def __init__(self, records=None):
        self.records = list(records or [])
        self.get_by_calls = []
        self.deleted_ids = []

    def get_by(self, **filters):
        self.get_by_calls.append(filters)

        def matched(record):
            for key, value in filters.items():
                if value is None:
                    continue
                # 查询参数 mtype 对应记录字段 type
                attr = "type" if key == "mtype" else key
                if getattr(record, attr, None) != value:
                    return False
            return True

        return [r for r in self.records if matched(r)]

    def delete(self, record_id):
        self.deleted_ids.append(record_id)
        return True


class FakeDownloadHistoryOper:
    def __init__(self, files=None, histories=None):
        self.files = list(files or [])
        self.histories = list(histories or [])
        self.deleted_file_paths = []

    def delete_file_by_fullpath(self, fullpath):
        self.deleted_file_paths.append(fullpath)
        return True

    def get_files_by_hash(self, download_hash):
        return [f for f in self.files if getattr(f, "download_hash", None) == download_hash]

    def get_files_by_fullpath(self, fullpath):
        return [f for f in self.files if getattr(f, "fullpath", None) == fullpath]

    def get_hash_by_fullpath(self, fullpath):
        for f in self.files:
            if getattr(f, "fullpath", None) == fullpath:
                return getattr(f, "download_hash", None)
        return None

    def get_by_hash(self, download_hash):
        for h in self.histories:
            if getattr(h, "download_hash", None) == download_hash:
                return h
        return None


class FakeDownloaderHelper:
    def __init__(self, services=None):
        self._services = services or {}

    def get_services(self):
        return self._services


class FakePluginBase:
    """模拟 _PluginBase 提供的数据、配置、消息与链路口子。"""

    def __init__(self):
        self.chain = FakeChain()
        self.eventmanager = eventmanager
        self._stored_data = {}
        self._stored_config = {}
        self.messages = []

    def get_data(self, key=None, plugin_id=None):
        return self._stored_data.get(plugin_id or "", {}).get(key)

    def save_data(self, key, value, plugin_id=None):
        self._stored_data.setdefault(plugin_id or "", {})[key] = value

    def del_data(self, key=None, plugin_id=None):
        self._stored_data.get(plugin_id or "", {}).pop(key, None)

    def update_config(self, config):
        self._stored_config = dict(config)

    def get_config(self, name=None):
        if name:
            return self._stored_config.get(name)
        return self._stored_config

    def post_message(self, **kwargs):
        self.messages.append(kwargs)
        return None


def _module(name, **attrs):
    module = types.ModuleType(name)
    module.__path__ = []
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def install_stubs():
    app = _module("app")
    app_schemas = _module("app.schemas", Response=Response, WebhookEventInfo=WebhookEventInfo)
    app_schemas_types = _module(
        "app.schemas.types",
        EventType=EventType,
        MediaImageType=MediaImageType,
        MediaSource=MediaSource,
        MediaType=MediaType,
        MessageType=MessageType,
    )
    app_schemas.types = app_schemas_types
    app_db = _module("app.db")
    app_db_oper = _module("app.db.oper")
    app_db_oper_downloadhistory = _module(
        "app.db.oper.downloadhistory", DownloadHistoryOper=FakeDownloadHistoryOper
    )
    app_db_oper_transferhistory = _module(
        "app.db.oper.transferhistory", TransferHistoryOper=FakeTransferHistoryOper
    )
    app_db.oper = app_db_oper
    app_db_oper.downloadhistory = app_db_oper_downloadhistory
    app_db_oper.transferhistory = app_db_oper_transferhistory
    app_plugins = _module("app.plugins", _PluginBase=FakePluginBase)
    app_sdk = _module("app.sdk")
    app_sdk_config = _module("app.sdk.config", settings=settings)
    app_sdk_events = _module("app.sdk.events", Event=FakeEvent, eventmanager=eventmanager)
    app_sdk_logging = _module("app.sdk.logging", logger=logger)
    app_sdk_media = _module(
        "app.sdk.media",
        build_media_key=build_media_key,
        resolve_media_identity=resolve_media_identity,
    )
    app_sdk_services = _module("app.sdk.services", DownloaderHelper=FakeDownloaderHelper)
    app_sdk_utilities = _module(
        "app.sdk.utilities", StringUtils=StringUtils, SystemUtils=SystemUtils
    )
    app_sdk.config = app_sdk_config
    app_sdk.events = app_sdk_events
    app_sdk.logging = app_sdk_logging
    app_sdk.media = app_sdk_media
    app_sdk.services = app_sdk_services
    app_sdk.utilities = app_sdk_utilities
    app.schemas = app_schemas
    app.db = app_db
    app.plugins = app_plugins
    app.sdk = app_sdk

    modules = {
        "app": app,
        "app.schemas": app_schemas,
        "app.schemas.types": app_schemas_types,
        "app.db": app_db,
        "app.db.oper": app_db_oper,
        "app.db.oper.downloadhistory": app_db_oper_downloadhistory,
        "app.db.oper.transferhistory": app_db_oper_transferhistory,
        "app.plugins": app_plugins,
        "app.sdk": app_sdk,
        "app.sdk.config": app_sdk_config,
        "app.sdk.events": app_sdk_events,
        "app.sdk.logging": app_sdk_logging,
        "app.sdk.media": app_sdk_media,
        "app.sdk.services": app_sdk_services,
        "app.sdk.utilities": app_sdk_utilities,
    }
    sys.modules.update(modules)
    return modules


def load_plugin_module(force_reload=False):
    install_stubs()
    if not force_reload and "linkedmediadel" in sys.modules:
        return sys.modules["linkedmediadel"]
    for name in [m for m in sys.modules if m == "linkedmediadel" or m.startswith("linkedmediadel.")]:
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(
        "linkedmediadel",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["linkedmediadel"] = module
    spec.loader.exec_module(module)
    return module
