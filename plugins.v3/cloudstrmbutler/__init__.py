import json
import hashlib
import os
import re
import shutil
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from watchdog.observers.polling import PollingObserver

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.core.metainfo import MetaInfoPath
from app.helper.mediaserver import MediaServerHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import MediaInfo
from app.schemas.types import EventType, NotificationType, MediaType
from app.utils.http import RequestUtils
from app.utils.string import StringUtils



from .config_rules import (
    MonitorRule,
    config_fingerprint,
    parse_comma_path_mappings,
    parse_monitor_confs,
    parse_path_mappings,
    serialize_mapping_line,
    serialize_path_mappings,
)
from .core_paths import (
    find_monitor_path,
    format_content,
    map_library_path,
    map_path,
    normalise_extensions,
    path_key,
    relative_path,
)
from .monitoring import FileMonitorHandler, is_ignored_path, is_temporary_path, wait_for_stable_file
from .state_store import SyncStateStore
class CloudStrmButler(_PluginBase):
    # 插件名称
    plugin_name = "云盘Strm小管家"
    plugin_name_en = "Cloud Strm Butler"
    # 插件描述
    plugin_desc = "Cloud Strm Butler - 实时监控、定时全量增量生成strm文件。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/luyang1104/MoviePilot-Plugins/main/icons/cloudstrm.png"
    # 插件版本
    plugin_version = "2.0.0"
    # 插件作者
    plugin_author = "FelixYang"
    # 作者主页
    author_url = ""
    # 插件配置项ID前缀
    plugin_config_prefix = "cloudstrmbutler_"
    # 加载顺序
    plugin_order = 26
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _monitor_confs = None
    _cover = False
    _monitor = False
    _onlyonce = False
    _copy_files = False
    _copy_subtitles = False
    _url = None
    _notify = False
    _refresh_emby = False
    _uriencode = False
    _strm_dir_conf = {}
    _cloud_dir_conf = {}
    _category_conf = {}
    _format_conf = {}
    _observer = []
    _medias = {}
    _rmt_mediaext = None
    _other_mediaext = None
    _interval: int = 10
    _scan_interval: int = 0
    _mediaservers = None
    mediaserver_helper = None
    _emby_paths = {}
    _path_replacements = {}  # 新增：路径替换规则属性

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None
    # 退出事件
    _event = threading.Event()

    _default_rmt_mediaext = ".mp4, .mkv, .ts, .iso,.rmvb, .avi, .mov, .mpeg,.mpg, .wmv, .3gp, .asf, .m4v, .flv, .m2ts, .strm,.tp, .f4v"
    _default_other_mediaext = ".nfo, .jpg, .png, .json"

    def __init__(self):
        super().__init__()
        self._reset_runtime_state()

    def _reset_runtime_state(self):
        self._enabled = False
        self._onlyonce = False
        self._monitor = False
        self._cover = False
        self._copy_files = False
        self._copy_subtitles = False
        self._refresh_emby = False
        self._notify = False
        self._uriencode = False
        self._interval = 10
        self._scan_interval = 0
        self._url = ""
        self._monitor_confs = ""
        self._rmt_mediaext = self._default_rmt_mediaext
        self._other_mediaext = self._default_other_mediaext
        self._media_extensions = set()
        self._other_extensions = set()
        self._strm_dir_conf = {}
        self._cloud_dir_conf = {}
        self._category_conf = {}
        self._format_conf = {}
        self._path_replacements = {}
        self._emby_paths = {}
        self._monitor_rules = []
        self._config_errors = []
        self._medias = {}
        self._observer = []
        self._scheduler = None
        self._event = threading.Event()
        self._media_lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._active_paths = set()
        self._scan_guard = threading.Lock()
        self._scan_running = False
        self._state_store = None
        self._config_fingerprint = ""

    def init_plugin(self, config: dict = None):
        self.stop_service()
        self._reset_runtime_state()

        migrated = False
        if not config:
            legacy_config = self.get_config("CloudStrmCompanion")
            if legacy_config:
                config = legacy_config
                migrated = True
                logger.info("已从 CloudStrmCompanion 迁移配置到 CloudStrmButler")

        self.mediaserver_helper = MediaServerHelper()

        if config:
            self._enabled = bool(config.get("enabled"))
            self._onlyonce = bool(config.get("onlyonce"))
            self._monitor = bool(config.get("monitor"))
            self._cover = bool(config.get("cover"))
            self._copy_files = bool(config.get("copy_files"))
            self._copy_subtitles = bool(config.get("copy_subtitles"))
            self._refresh_emby = bool(config.get("refresh_emby"))
            self._notify = bool(config.get("notify"))
            self._uriencode = bool(config.get("uriencode"))
            self._url = str(config.get("url") or "")
            self._monitor_confs = str(config.get("monitor_confs") or "")
            self._mediaservers = config.get("mediaservers") or []
            self._other_mediaext = config.get("other_mediaext") or self._default_other_mediaext
            try:
                self._interval = max(0, int(config.get("interval") or 10))
            except (TypeError, ValueError):
                self._interval = 10
            try:
                self._scan_interval = max(0, int(config.get("scan_interval") or 0))
            except (TypeError, ValueError):
                self._scan_interval = 0
            self._path_replacements = dict(parse_path_mappings(config.get("path_replacements")))
            self._rmt_mediaext = config.get("rmt_mediaext") or self._default_rmt_mediaext
            self._emby_paths = dict(parse_comma_path_mappings(config.get("emby_path")))
            # 结构化规则优先：从 rule_N_* 键生成 monitor_confs
            structured_rules = self._parse_structured_rules(config)
            if structured_rules:
                self._monitor_confs = self._rules_to_monitor_confs(structured_rules)
                # 清理旧的结构化槽位，写回规范化配置
                normalized = dict(config)
                for key in list(normalized.keys()):
                    if key.startswith("rule_"):
                        normalized.pop(key, None)
                for i, rule in enumerate(structured_rules):
                    normalized[f"rule_{i}_category"] = rule.get("category", "")
                    normalized[f"rule_{i}_local"] = rule.get("local", "")
                    normalized[f"rule_{i}_strm"] = rule.get("strm", "")
                    normalized[f"rule_{i}_cloud"] = rule.get("cloud", "")
                    normalized[f"rule_{i}_format"] = rule.get("format", "")
                    normalized[f"rule_{i}_monitor"] = rule.get("monitor", True)
                normalized["monitor_confs"] = self._monitor_confs
                if normalized != config:
                    try:
                        self.update_config(normalized)
                    except Exception:
                        pass

        if migrated:
            self.__update_config()

        self._media_extensions = normalise_extensions(self._rmt_mediaext)
        self._other_extensions = normalise_extensions(self._other_mediaext)
        self._monitor_rules, self._config_errors = parse_monitor_confs(self._monitor_confs)
        for rule in self._monitor_rules:
            self._strm_dir_conf[rule.local_dir] = rule.strm_dir
            self._cloud_dir_conf[rule.local_dir] = rule.cloud_dir
            self._format_conf[rule.local_dir] = rule.format_str
            self._category_conf[rule.local_dir] = rule.category
        self._config_fingerprint = config_fingerprint(
            self._monitor_rules,
            self._path_replacements,
            self._emby_paths,
            self._media_extensions,
            self._other_extensions,
            self._cover,
            self._copy_files,
            self._copy_subtitles,
            self._uriencode,
        )
        self._state_store = SyncStateStore(self.get_data_path() / "sync_state.sqlite3")

        for error in self._config_errors:
            logger.error(error)
            self.systemmessage.put(error)

        if not (self._enabled or self._onlyonce):
            return

        if not self._monitor_rules:
            logger.warning("没有可用的目录配置，不启动扫描任务")
            if self._onlyonce:
                self._onlyonce = False
                self.__update_config()
            return

        self._scheduler = BackgroundScheduler(timezone=settings.TZ)

        if self._notify:
            self._scheduler.add_job(
                self.send_msg,
                trigger="interval",
                seconds=15,
                name="云盘Strm小管家通知队列",
            )

        if self._scan_interval > 0:
            self._scheduler.add_job(
                func=self.scan,
                trigger="interval",
                minutes=self._scan_interval,
                name="云盘Strm小管家周期全量扫描",
            )

        for rule in self._monitor_rules:
            if rule.should_monitor(self._monitor):
                self._start_observer(rule)

        if self._onlyonce:
            self._scheduler.add_job(
                func=self.scan,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="云盘Strm小管家一次性全量扫描",
            )
            self._onlyonce = False
            self.__update_config()

        if self._scheduler.get_jobs():
            self._scheduler.print_jobs()
            self._scheduler.start()

    def _start_observer(self, rule: MonitorRule):
        """Start a polling watcher for one valid monitor rule."""
        try:
            observer = PollingObserver(timeout=10)
            observer.schedule(FileMonitorHandler(rule.local_dir, self), path=rule.local_dir, recursive=True)
            observer.daemon = True
            observer.start()
            self._observer.append(observer)
            logger.info(f"{rule.local_dir} 的 Strm 生成实时监控服务启动")
        except Exception as exc:
            message = str(exc)
            if "inotify" in message and "reached" in message:
                logger.warning(
                    f"云盘实时监控服务启动出现异常：{message}，请在宿主机上（不是 docker 容器内）执行以下命令并重启："
                    "echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf\n"
                    "echo fs.inotify.max_user_instances=524288 | sudo tee -a /etc/sysctl.conf\n"
                    "sudo sysctl -p"
                )
            else:
                logger.error(f"{rule.local_dir} 启动实时监控失败：{message}")
            self.systemmessage.put(f"{rule.local_dir} 启动实时监控失败：{message}")

    def scan(self):
        """Run an idempotent full directory reconciliation."""
        if not self._scan_guard.acquire(blocking=False):
            logger.warning("已有增量扫描正在执行，跳过本次请求")
            return
        self._scan_running = True
        started = time.monotonic()
        try:
            logger.info("开始增量执行")
            for rule in self._monitor_rules:
                self._scan_rule(rule)
            logger.info("增量执行完成，耗时 %.1f 秒", time.monotonic() - started)
        finally:
            self._scan_running = False
            self._scan_guard.release()

    def _scan_rule(self, rule: MonitorRule):
        """Walk one monitor root and reconcile it with the persisted index."""
        if not Path(rule.local_dir).is_dir():
            logger.error(f"监控目录不可用：{rule.local_dir}")
            return
        seen = set()
        completed = True
        try:
            for root, _dirs, files in os.walk(rule.local_dir):
                for file_name in files:
                    source_file = os.path.join(root, file_name)
                    relative = relative_path(source_file, rule.local_dir)
                    if relative is None:
                        continue
                    seen.add(str(relative).replace("\\", "/"))
                    if is_ignored_path(source_file) or is_temporary_path(source_file):
                        continue
                    self.__handle_file(event_path=source_file, mon_path=rule.local_dir)
        except OSError as exc:
            completed = False
            logger.error(f"遍历监控目录失败：{rule.local_dir} - {exc}")

        if completed and self._state_store is not None:
            for record in self._state_store.reap(rule.local_dir, seen):
                self._remove_outputs(
                    record.outputs,
                    notify_emby=bool(record.content_hash),
                )

    @eventmanager.register(EventType.PluginAction)
    def strm_one(self, event: Event = None):
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "cloudstrm_file":
                return
            file_path = event_data.get("file_path")
            if not file_path:
                logger.error(f"缺少参数：{event_data}")
                return

            # 遍历所有监控目录
            mon_path = find_monitor_path(file_path, self._strm_dir_conf)

            if not mon_path:
                logger.error(f"未找到文件 {file_path} 对应的监控目录")
                return

            # 处理单文件
            self.__handle_file(event_path=file_path, mon_path=mon_path)

    @eventmanager.register(EventType.PluginAction)
    def remote_sync(self, event: Event = None):
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "CloudStrmButler":
                return
            logger.info("开始云盘Strm小管家全量同步")
            self.scan()

    def event_handler(self, event, mon_path: str, text: str, event_path: str, **kwargs):
        """Handle create/modify/move/delete events from watchdog."""
        if getattr(event, "is_directory", False):
            return
        if is_ignored_path(event_path) or is_temporary_path(event_path):
            return

        action = kwargs.get("action", "created")
        old_event_path = kwargs.get("old_event_path")
        if action == "deleted":
            logger.debug("监控到文件%s：%s", text, event_path)
            self.__handle_deleted_file(event_path=event_path, mon_path=mon_path)
            return

        if old_event_path and old_event_path != event_path:
            self.__handle_deleted_file(event_path=old_event_path, mon_path=mon_path)

        logger.debug("监控到文件%s：%s", text, event_path)
        self.__handle_file(event_path=event_path, mon_path=mon_path, wait_stable=True)

    @staticmethod
    def __remap_path(event_path: str, source_root: str, target_root: str) -> Optional[str]:
        """Map one local path from a monitor root to another root."""
        return map_path(event_path, source_root, target_root)

    def __wait_stable_file(self, event_path: str, max_wait: int = 30) -> bool:
        """Wait until the source file stops changing."""
        return wait_for_stable_file(event_path, max_wait=max_wait)

    def __handle_file(self, event_path: str, mon_path: str, wait_stable: bool = False):
        """Synchronize one source file and persist its state signature."""
        source = Path(event_path)
        if not source.exists() or not source.is_file():
            return {"status": "missing"}
        if is_ignored_path(event_path) or is_temporary_path(event_path):
            return {"status": "ignored"}
        if wait_stable and not self.__wait_stable_file(event_path):
            return {"status": "unstable"}

        source_rel = relative_path(event_path, mon_path)
        if source_rel is None:
            logger.error(f"文件 {event_path} 不在监控目录 {mon_path} 下")
            return {"status": "outside_root"}

        active_key = path_key(event_path)
        with self._active_lock:
            if active_key in self._active_paths:
                return {"status": "duplicate"}
            self._active_paths.add(active_key)

        outputs: List[str] = []
        try:
            stat = source.stat()
            mtime_ns = int(getattr(stat, "st_mtime_ns", stat.st_mtime * 1_000_000_000))
            size = int(stat.st_size)
            cloud_dir = self._cloud_dir_conf.get(mon_path)
            strm_dir = self._strm_dir_conf.get(mon_path)
            format_str = self._format_conf.get(mon_path)
            target_file = self.__remap_path(event_path, mon_path, strm_dir)
            cloud_file = self.__remap_path(event_path, mon_path, cloud_dir)
            if not target_file:
                logger.error(f"无法计算文件 {event_path} 的目标路径")
                return {"status": "invalid_target"}
            if not cloud_file and "{cloud_file}" in (format_str or ""):
                logger.error(f"无法计算文件 {event_path} 的云盘路径")
                return {"status": "invalid_cloud"}

            suffix = source.suffix.lower()
            content_hash = ""
            if suffix in self._media_extensions:
                strm_content = self.__format_content(
                    format_str=format_str,
                    local_file=event_path,
                    cloud_file=str(cloud_file),
                    uriencode=self._uriencode,
                )
                if not strm_content:
                    logger.error(f"文件 {event_path} 的 STRM 模板无效")
                    return {"status": "invalid_content"}
                strm_content = self._apply_path_replacements(strm_content)
                content_hash = hashlib.sha256(strm_content.encode("utf-8")).hexdigest()
                sidecar_paths = list(self._iter_sidecars(source))
                strm_target = str(Path(target_file).with_suffix(".strm"))
                expected_outputs = [strm_target]
                expected_outputs.extend(
                    sidecar_target
                    for sidecar_path in sidecar_paths
                    if self._should_copy_sidecar(str(sidecar_path))
                    if (sidecar_target := self.__remap_path(str(sidecar_path), mon_path, strm_dir))
                )
                if not self._cover and self._record_is_current(
                    source_rel, mtime_ns, size, content_hash, mon_path, expected_outputs
                ):
                    return {"status": "unchanged"}
                strm_output = self.__create_strm_file(strm_file=target_file, strm_content=strm_content, source_file=event_path)
                if strm_output:
                    outputs.append(strm_output)
                for sidecar_path in sidecar_paths:
                    sidecar_target = self.__remap_path(str(sidecar_path), mon_path, strm_dir)
                    if sidecar_target:
                        outputs.extend(
                            self.__handle_other_files(str(sidecar_path), sidecar_target)
                        )
            else:
                sidecar_expected = [
                    target_file
                ] if (
                    (self._copy_files and suffix in self._other_extensions)
                    or (self._copy_subtitles and suffix in {".srt", ".ass", ".ssa", ".sub"})
                ) else []
                if not self._cover and self._record_is_current(
                    source_rel, mtime_ns, size, content_hash, mon_path, sidecar_expected
                ):
                    return {"status": "unchanged"}
                outputs.extend(self.__handle_other_files(event_path, target_file))

            if self._state_store is not None:
                self._state_store.upsert(
                    monitor_root=mon_path,
                    source_rel=str(source_rel),
                    mtime_ns=mtime_ns,
                    size=size,
                    content_hash=content_hash,
                    outputs=outputs,
                    config_fingerprint=self._config_fingerprint,
                )
            return {"status": "processed", "outputs": outputs}
        except Exception as exc:
            logger.error("目录监控发生错误：%s - %s", str(exc), traceback.format_exc())
            return {"status": "failed", "reason": str(exc)}
        finally:
            with self._active_lock:
                self._active_paths.discard(active_key)

    def _should_copy_sidecar(self, event_path: str) -> bool:
        suffix = Path(event_path).suffix.lower()
        return (
            (self._copy_files and suffix in self._other_extensions)
            or (self._copy_subtitles and suffix in {".srt", ".ass", ".ssa", ".sub"})
        )

    def __handle_other_files(self, event_path: str, target_file: str):
        """Copy a sidecar when configured and return its target path."""
        if not target_file:
            return []
        outputs: List[str] = []
        suffix = Path(event_path).suffix.lower()
        if self._copy_files and suffix in self._other_extensions:
            output = self.__copy_sidecar_file(event_path, target_file, "非媒体文件")
            if output:
                outputs.append(output)
        if self._copy_subtitles and suffix in {".srt", ".ass", ".ssa", ".sub"}:
            output = self.__copy_sidecar_file(event_path, target_file, "字幕文件")
            if output:
                outputs.append(output)
        return outputs

    def __copy_sidecar_file(self, event_path: str, target_file: str, kind: str):
        """Copy one sidecar and return the output path when successful."""
        try:
            target_dir = os.path.dirname(target_file)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(str(event_path), target_file)
            logger.info(f"复制{kind} {str(event_path)} 到 {target_file}")
            return target_file
        except PermissionError:
            logger.error(f"复制{kind}失败：目标目录没有写入权限 {os.path.dirname(target_file)}")
        except Exception as exc:
            logger.error(f"复制{kind}失败：{exc}")
        return None



    def _record_is_current(
        self,
        source_rel,
        mtime_ns: int,
        size: int,
        content_hash: str,
        mon_path: str,
        expected_outputs=None,
    ) -> bool:
        if self._state_store is None:
            return False
        record = self._state_store.get(mon_path, str(source_rel))
        if not record:
            return False
        if record.config_fingerprint != self._config_fingerprint:
            return False
        if record.mtime_ns != mtime_ns or record.size != size or record.content_hash != content_hash:
            return False
        if not all(Path(output).exists() for output in record.outputs):
            return False
        if expected_outputs is None:
            return True
        recorded = {path_key(output) for output in record.outputs}
        return all(
            path_key(output) in recorded and Path(output).exists()
            for output in expected_outputs
        )

    def _apply_path_replacements(self, content: str) -> str:
        for source, target in self._path_replacements.items():
            if source in content:
                content = content.replace(source, target)
                logger.debug(f"应用路径替换规则: {source} -> {target}")
        return content

    @staticmethod
    def _iter_sidecars(source: Path):
        stem = source.stem
        for sibling in source.parent.iterdir():
            if sibling.is_file() and sibling != source and sibling.stem == stem:
                yield sibling
        thumb = source.parent / f"{stem}-thumb.jpg"
        if thumb.is_file():
            yield thumb

    def __handle_deleted_file(self, event_path: str, mon_path: str):
        """Remove generated outputs and the persisted record for a deleted source."""
        if self._state_store is None:
            return
        source_rel = relative_path(event_path, mon_path)
        if source_rel is None:
            return
        record = self._state_store.delete(mon_path, str(source_rel))
        if record:
            self._remove_outputs(record.outputs, notify_emby=bool(record.content_hash))

    def _remove_outputs(self, outputs, notify_emby: bool = False):
        """Remove only files that are recorded as generated by this plugin."""
        for output in outputs or []:
            path = Path(output)
            try:
                path.unlink(missing_ok=True)
                logger.info(f"已清理生成文件 {path}")
            except OSError as exc:
                logger.warning(f"清理生成文件失败 {path}：{exc}")
            if notify_emby and path.suffix.lower() == ".strm" and self._refresh_emby:
                try:
                    self.__refresh_emby_file(str(path), update_type="Deleted")
                except Exception as exc:
                    logger.warning(f"通知 Emby 删除失败 {path}：{exc}")

    @staticmethod
    def __format_content(format_str: str, local_file: str, cloud_file: str, uriencode: bool):
        """Render a STRM template."""
        return format_content(format_str, local_file, cloud_file, uriencode)

    def __create_strm_file(self, strm_file: str, strm_content: str, source_file: str = None) -> Optional[str]:
        """Write a STRM file atomically and trigger optional post-processing."""
        if not strm_content:
            logger.error(f"STRM 内容为空：{strm_file}")
            return None
        try:
            parent = Path(strm_file).parent
            if not parent.exists():
                logger.info(f"创建目标文件夹 {parent}")
                parent.mkdir(parents=True, exist_ok=True)

            strm_file = str(parent / f"{Path(strm_file).stem}.strm")
            if Path(strm_file).exists() and not self._cover:
                logger.debug(f"目标文件 {strm_file} 已存在")
                return strm_file

            temp_file = Path(strm_file).with_name(f".{Path(strm_file).name}.tmp")
            with temp_file.open("w", encoding="utf-8", newline="") as file:
                file.write(strm_content)
            os.replace(str(temp_file), strm_file)
            logger.info(f"创建strm文件成功 {strm_file} -> {strm_content}")

            source_suffix = Path(source_file).suffix.lower() if source_file else ""
            if self._url and source_suffix in self._media_extensions:
                try:
                    response = RequestUtils(content_type="application/json").post(
                        url=self._url,
                        json={"path": strm_content, "type": "add"},
                    )
                    if response is None or getattr(response, "status_code", 0) not in range(200, 300):
                        logger.warning(f"任务推送失败：{strm_file}")
                except Exception as exc:
                    logger.warning(f"任务推送异常：{exc}")

            if self._notify and source_suffix in self._media_extensions:
                self._record_media_notification(strm_file)
            if self._refresh_emby and self._mediaservers:
                self.__refresh_emby_file(strm_file)
            return strm_file
        except Exception as exc:
            logger.error(f"创建strm文件失败 {strm_file} -> {exc}")
        return None

    def _record_media_notification(self, strm_file: str):
        """Queue a media notification entry behind a dedicated lock."""
        file_meta = MetaInfoPath(Path(strm_file))
        match = re.search(r"tmdbid=(\d+)", strm_file)
        if match:
            file_meta.tmdbid = match.group(1)
        key = f"{file_meta.cn_name} ({file_meta.year}){f' {file_meta.season}' if file_meta.season else ''}"
        with self._media_lock:
            media_list = self._medias.get(key) or {}
            episodes = list(media_list.get("episodes") or [])
            if file_meta.begin_episode:
                episode = int(file_meta.begin_episode)
                if episode not in episodes:
                    episodes.append(episode)
            self._medias[key] = {
                "episodes": episodes,
                "file_meta": file_meta,
                "type": "tv" if file_meta.season else "movie",
                "time": datetime.now(),
            }

    def __refresh_emby_file(self, strm_file: str, update_type: str = "Created"):
        """Notify configured Emby servers and keep failures observable."""
        emby_servers = self.mediaserver_helper.get_services(
            name_filters=self._mediaservers, type_filter="emby"
        )
        if not emby_servers:
            logger.error("未配置Emby媒体服务器")
            return
        mapped_file = self.__get_path(paths=self._emby_paths, file_path=strm_file)
        for emby_name, emby_server in emby_servers.items():
            emby = emby_server.instance
            try:
                res = emby.post_data(
                    url="[HOST]emby/Library/Media/Updated?api_key=[APIKEY]&reqformat=json",
                    data=json.dumps({
                        "Updates": [{"Path": mapped_file, "UpdateType": update_type}]
                    }),
                    headers={"Content-Type": "application/json"},
                )
                if res and res.status_code in [200, 204]:
                    logger.info(f"媒体服务器 {emby_name} 已刷新 {mapped_file}")
                else:
                    status_code = getattr(res, "status_code", "无响应")
                    logger.error(f"通知媒体服务器 {emby_name} 失败，错误码：{status_code}")
            except Exception as err:
                logger.error(f"通知媒体服务器 {emby_name} 失败：{err}")

    def __get_path(self, paths, file_path: str):
        """Map a local file path using the longest matching library root."""
        return map_library_path(paths or {}, file_path)

    @eventmanager.register(EventType.PluginAction)
    def remote_sync_one(self, event: Event = None):
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "strm_one":
                return
            args = event_data.get("arg_str")
            if not args:
                logger.error(f"缺少参数：{event_data}")
                return
            all_args = args

            # 使用正则表达式匹配
            category = None
            args_arr = args.split(maxsplit=1)
            limit = None
            if len(args_arr) == 2:
                category = args_arr[0]
                args = args_arr[1]
                if str(args).isdigit():
                    limit = int(args)

            if category:
                # 判断是不是目录
                if Path(category).is_dir() and Path(category).exists() and limit is not None:
                    # 遍历所有监控目录
                    mon_path = find_monitor_path(category, self._category_conf)

                    # 指定路径
                    if not mon_path:
                        logger.error(f"未找到 {category} 对应的监控目录")
                        self.post_message(channel=event.event_data.get("channel"),
                                          title=f"未找到 {category} 对应的监控目录",
                                          userid=event.event_data.get("user"))
                        return

                    self.__handle_limit(path=category, mon_path=mon_path, limit=limit, event=event)
                    return
                else:
                    for mon_path in self._category_conf.keys():
                        mon_category = self._category_conf.get(mon_path)
                        logger.info(f"开始检查 {mon_path} {mon_category}")
                        mon_categories = [t.strip() for t in str(mon_category or "").split(",") if t.strip()]
                        if mon_category and str(category) in mon_categories + [mon_category]:
                            parent_path = os.path.join(mon_path, category)
                            if limit:
                                logger.info(f"获取到 {category} 对应的监控目录 {parent_path}")
                                self.__handle_limit(path=parent_path, mon_path=mon_path, limit=limit, event=event)
                            else:
                                logger.info(f"获取到 {category} {args} 对应的监控目录 {parent_path}")
                                target_path = os.path.join(str(parent_path), args)
                                logger.info(f"开始处理 {target_path}")
                                target_paths = self.__find_related_paths(os.path.join(str(parent_path), args))
                                if not target_paths:
                                    logger.error(f"未查找到 {category} {args} 对应的具体目录")
                                    self.post_message(channel=event.event_data.get("channel"),
                                                      title=f"未查找到 {category} {args} 对应的具体目录",
                                                      userid=event.event_data.get("user"))
                                    return
                                for target_path in target_paths:
                                    logger.info(f"开始定向处理文件夹 ...{target_path}")
                                    for sroot, sdirs, sfiles in os.walk(target_path):
                                        for file_name in sdirs + sfiles:
                                            src_file = os.path.join(sroot, file_name)
                                            if Path(src_file).is_file():
                                                self.__handle_file(event_path=str(src_file), mon_path=mon_path)

                                    if event.event_data.get("user"):
                                        self.post_message(channel=event.event_data.get("channel"),
                                                          title=f"{target_path} Strm生成完成！",
                                                          userid=event.event_data.get("user"))
                                    time.sleep(2)

                                    if limit is None and event_data and event_data.get("action") == "strm_one":
                                        return
                            return
            else:
                # 遍历所有监控目录
                mon_path = find_monitor_path(args, self._category_conf)

                # 指定路径
                if mon_path:
                    if not Path(args).exists():
                        logger.info(f"同步路径 {args} 不存在")
                        return
                    # 处理单文件
                    if Path(args).is_file():
                        self.__handle_file(event_path=str(args), mon_path=mon_path)
                        return
                    else:
                        # 处理指定目录
                        logger.info(f"获取到 {args} 对应的监控目录 {mon_path}")

                        logger.info(f"开始定向处理文件夹 ...{args}")
                        for sroot, sdirs, sfiles in os.walk(args):
                            for file_name in sdirs + sfiles:
                                src_file = os.path.join(sroot, file_name)
                                if Path(str(src_file)).is_file():
                                    self.__handle_file(event_path=str(src_file), mon_path=mon_path)
                        if event.event_data.get("user"):
                            self.post_message(channel=event.event_data.get("channel"),
                                              title=f"{all_args} Strm生成完成！", userid=event.event_data.get("user"))
                        return
                else:
                    for mon_path in self._category_conf.keys():
                        mon_category = self._category_conf.get(mon_path)
                        logger.info(f"开始检查 {mon_path} {mon_category}")
                        mon_categories = [t.strip() for t in str(mon_category or "").split(",") if t.strip()]
                        if mon_category and str(args) in mon_categories + [mon_category]:
                            parent_path = os.path.join(mon_path, args)
                            logger.info(f"获取到 {args} 对应的监控目录 {parent_path}")
                            for sroot, sdirs, sfiles in os.walk(parent_path):
                                for file_name in sdirs + sfiles:
                                    src_file = os.path.join(sroot, file_name)
                                    if Path(str(src_file)).is_file():
                                        self.__handle_file(event_path=str(src_file), mon_path=mon_path)
                            if event.event_data.get("user"):
                                self.post_message(channel=event.event_data.get("channel"),
                                                  title=f"{all_args} Strm生成完成！",
                                                  userid=event.event_data.get("user"))
                            return
            if event.event_data.get("user"):
                self.post_message(channel=event.event_data.get("channel"),
                                  title=f"{all_args} 未检索到，请检查输入是否正确！",
                                  userid=event.event_data.get("user"))

    @staticmethod
    def __find_related_paths(base_path):
        related_paths = []
        base_dir = os.path.dirname(base_path)
        base_name = os.path.basename(base_path)

        for entry in os.listdir(base_dir):
            if entry.startswith(base_name):
                full_path = os.path.join(base_dir, entry)
                if os.path.isdir(full_path):
                    related_paths.append(full_path)

        # 按照修改时间倒序排列
        related_paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)

        return related_paths

    def __handle_limit(self, path, limit, mon_path, event):
        """
        处理文件数量限制
        """
        sub_paths = []
        for entry in os.listdir(path):
            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path):
                sub_paths.append(full_path)

        if not sub_paths:
            logger.error(f"未找到 {path} 目录下的文件夹")
            return

        # 按照修改时间倒序排列
        sub_paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        logger.info(f"开始定向处理文件夹 ...{path}, 最新 {limit} 个文件夹")
        for sub_path in sub_paths[:limit]:
            logger.info(f"开始定向处理文件夹 ...{sub_path}")
            for sroot, sdirs, sfiles in os.walk(sub_path):
                for file_name in sdirs + sfiles:
                    src_file = os.path.join(sroot, file_name)
                    if Path(src_file).is_file():
                        self.__handle_file(event_path=str(src_file), mon_path=mon_path)
            if event.event_data.get("user"):
                self.post_message(channel=event.event_data.get("channel"),
                                  title=f"{sub_path} Strm生成完成！", userid=event.event_data.get("user"))
            time.sleep(2)

    def send_msg(self):
        """Check queued media notifications and send stale entries."""
        with self._media_lock:
            snapshot = list(self._medias.items())
        for key, media_list in snapshot:
            if not media_list:
                continue
            last_update_time = media_list.get("time")
            if not last_update_time:
                continue
            mtype = media_list.get("type")
            if (datetime.now() - last_update_time).total_seconds() <= int(self._interval) \
                    and str(mtype) != "movie":
                continue
            try:
                if self._notify:
                    file_meta = media_list.get("file_meta")
                    episodes = media_list.get("episodes") or []
                    file_count = len(episodes) if episodes else 1
                    if str(mtype) == "tv":
                        season_episode = f"{key} {StringUtils.format_ep(episodes)}"
                        media_type = MediaType.TV
                    else:
                        season_episode = key
                        media_type = MediaType.MOVIE
                    mediainfo = self.chain.recognize_media(
                        meta=file_meta, mtype=media_type, tmdbid=file_meta.tmdbid
                    )
                    image = None
                    if mediainfo:
                        image = mediainfo.backdrop_path or mediainfo.poster_path
                    self.send_transfer_message(season_episode, file_count, image)
            except Exception as exc:
                logger.warning(f"发送媒体消息失败 {key}：{exc}")
            with self._media_lock:
                if self._medias.get(key) is media_list:
                    self._medias.pop(key, None)

    def send_transfer_message(self, msg_title, file_count, image):
        """
        发送消息
        """
        # 发送
        self.post_message(
            mtype=NotificationType.Plugin,
            title=f"{msg_title} Strm已生成", text=f"共{file_count}个文件",
            image=image,
            link=settings.MP_DOMAIN('#/history'))

    def __update_config(self):
        """
        更新配置：保存时同时写入结构化 rule_N_* 键和 monitor_confs。
        """
        payload = {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cover": self._cover,
            "notify": self._notify,
            "monitor": self._monitor,
            "interval": self._interval,
            "scan_interval": self._scan_interval,
            "copy_files": self._copy_files,
            "copy_subtitles": self._copy_subtitles,
            "refresh_emby": self._refresh_emby,
            "url": self._url,
            "monitor_confs": self._monitor_confs,
            "rmt_mediaext": self._rmt_mediaext,
            "other_mediaext": self._other_mediaext,
            "mediaservers": self._mediaservers,
            "uriencode": self._uriencode,
            "emby_path": ",".join(serialize_mapping_line(source, target) for source, target in self._emby_paths.items()),
            "path_replacements": serialize_path_mappings(list(self._path_replacements.items())),
        }
        # 写入结构化规则键供 Vue 组件读取
        for i, rule in enumerate(self._monitor_rules):
            payload[f"rule_{i}_category"] = rule.category or ""
            payload[f"rule_{i}_local"] = rule.local_dir
            payload[f"rule_{i}_strm"] = rule.strm_dir
            payload[f"rule_{i}_cloud"] = rule.cloud_dir
            payload[f"rule_{i}_format"] = rule.format_str
            payload[f"rule_{i}_monitor"] = rule.monitor_override != "nomonitor"
            payload[f"rule_{i}_delete"] = False
        self.update_config(payload)

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """声明插件使用 Vue 联邦组件渲染配置页面。"""
        return "vue", "dist/assets"

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [
            {
                "cmd": "/cloud_strm_butler",
                "event": EventType.PluginAction,
                "desc": "云盘Strm助手同步",
                "category": "",
                "data": {
                    "action": "CloudStrmButler"
                }
            },
            {
                "cmd": "/strm",
                "event": EventType.PluginAction,
                "desc": "定向云盘Strm同步",
                "category": "",
                "data": {
                    "action": "strm_one"
                }
            },
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """Vue 模式：返回空表单和完整配置模型。"""
        saved = self.get_config() or {}
        rules = self._parse_structured_rules(saved)

        model = {
            "enabled": self._enabled,
            "monitor": self._monitor,
            "cover": self._cover,
            "notify": self._notify,
            "copy_files": self._copy_files,
            "copy_subtitles": self._copy_subtitles,
            "refresh_emby": self._refresh_emby,
            "uriencode": self._uriencode,
            "onlyonce": self._onlyonce,
            "interval": self._interval,
            "scan_interval": self._scan_interval,
            "url": self._url,
            "rmt_mediaext": self._rmt_mediaext,
            "other_mediaext": self._other_mediaext,
            "emby_path": self._emby_path_serialized(),
            "path_replacements": self._path_replacements_serialized(),
            "mediaservers": self._mediaservers or [],
            "monitor_confs": self._monitor_confs,
        }
        for i, rule in enumerate(rules):
            model[f"rule_{i}_category"] = rule.get("category", "")
            model[f"rule_{i}_local"] = rule.get("local", "")
            model[f"rule_{i}_strm"] = rule.get("strm", "")
            model[f"rule_{i}_cloud"] = rule.get("cloud", "")
            model[f"rule_{i}_format"] = rule.get("format", "")
            model[f"rule_{i}_monitor"] = rule.get("monitor", True)
            model[f"rule_{i}_delete"] = False
        return [], model

    def _parse_structured_rules(self, config: dict) -> list:
        """从结构化 rule_N_* 键或旧 monitor_confs 解析规则列表。"""
        rules = []
        structured_slots = 0
        for key in (config or {}).keys():
            if str(key).startswith("rule_") and (str(key).endswith("_local") or str(key).endswith("_strm")):
                try:
                    idx = int(str(key).split("_")[1])
                    structured_slots = max(structured_slots, idx + 1)
                except (ValueError, IndexError):
                    pass

        has_structured = any(
            str(config.get(f"rule_{i}_local") or "").strip() or str(config.get(f"rule_{i}_strm") or "").strip()
            for i in range(structured_slots)
        )

        if has_structured:
            for i in range(structured_slots):
                delete_val = str(config.get(f"rule_{i}_delete") or "").strip().lower()
                if delete_val in ("1", "true", "yes", "on"):
                    continue
                local = str(config.get(f"rule_{i}_local") or "").strip()
                strm = str(config.get(f"rule_{i}_strm") or "").strip()
                if not local and not strm:
                    continue
                rules.append({
                    "category": str(config.get(f"rule_{i}_category") or ""),
                    "local": local,
                    "strm": strm,
                    "cloud": str(config.get(f"rule_{i}_cloud") or "").strip(),
                    "format": str(config.get(f"rule_{i}_format") or "").strip(),
                    "monitor": bool(config.get(f"rule_{i}_monitor", True)),
                })
            return rules

        # Fallback to legacy monitor_confs
        for raw_line in str(config.get("monitor_confs") or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            monitor_flag = None
            if line.count("$") == 1:
                line, monitor_flag = line.split("$", 1)
                monitor_flag = monitor_flag.strip()
            category = None
            if line.count("@") == 1:
                line, category = line.split("@", 1)
                category = category.strip()
            if line.count("#") < 3:
                continue
            local_dir, strm_dir, cloud_dir, format_str = [p.strip() for p in line.split("#", 3)]
            if not local_dir or not strm_dir:
                continue
            rules.append({
                "category": category or "",
                "local": local_dir,
                "strm": strm_dir,
                "cloud": cloud_dir,
                "format": format_str,
                "monitor": monitor_flag != "0",
            })
        return rules

    @staticmethod
    def _rules_to_monitor_confs(rules: list) -> str:
        """把规则列表序列化为旧版 monitor_confs 文本。"""
        lines = []
        for rule in rules or []:
            local = str(rule.get("local") or "").strip()
            strm = str(rule.get("strm") or "").strip()
            if not local or not strm:
                continue
            category_str = str(rule.get("category") or "").strip()
            cloud = str(rule.get("cloud") or "").strip()
            fmt = str(rule.get("format") or "").strip()
            line = f"{local}#{strm}#{cloud}#{fmt}"
            if category_str:
                line += f"@{category_str}"
            if not rule.get("monitor", True):
                line += "$0"
            lines.append(line)
        return "\n".join(lines)

    def _emby_path_serialized(self) -> str:
        return ",".join(f"{s}=>{t}" for s, t in self._emby_paths.items())

    def _path_replacements_serialized(self) -> str:
        return "\n".join(f"{s}=>{t}" for s, t in self._path_replacements.items())

    def get_page(self) -> List[dict]:
        """Vue 模式：详情页由远程 Page 组件渲染。"""
        return []

    def stop_service(self):
        """
        退出插件
        """
        if self._observer:
            for observer in self._observer:
                try:
                    observer.stop()
                    observer.join(timeout=10)
                except Exception as e:
                    logger.warning(f"停止目录监控失败：{e}")
        self._observer = []
        if self._scheduler:
            self._scheduler.remove_all_jobs()
            if self._scheduler.running:
                self._event.set()
                self._scheduler.shutdown()
                self._event.clear()
            self._scheduler = None
        if self._state_store:
            self._state_store.close()
            self._state_store = None
