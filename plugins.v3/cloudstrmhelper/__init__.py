import json
import os
import re
import shutil
import threading
import time
import traceback
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from watchdog.events import FileSystemEventHandler
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

lock = threading.Lock()


class FileMonitorHandler(FileSystemEventHandler):
    """
    目录监控响应类
    """

    def __init__(self, monpath: str, sync: Any, **kwargs):
        super(FileMonitorHandler, self).__init__(**kwargs)
        self._watch_path = monpath
        self.sync = sync

    def on_created(self, event):
        self.sync.event_handler(event=event, text="创建",
                                mon_path=self._watch_path, event_path=event.src_path,
                                action="created")

    def on_modified(self, event):
        self.sync.event_handler(event=event, text="修改",
                                mon_path=self._watch_path, event_path=event.src_path,
                                action="modified")

    def on_moved(self, event):
        self.sync.event_handler(event=event, text="移动",
                                mon_path=self._watch_path, event_path=event.dest_path,
                                old_event_path=event.src_path, action="moved")

    def on_deleted(self, event):
        self.sync.event_handler(event=event, text="删除",
                                mon_path=self._watch_path, event_path=event.src_path,
                                action="deleted")


class CloudStrmHelper(_PluginBase):
    # 插件名称
    plugin_name = "CloudStrm"
    # 插件描述
    plugin_desc = "实时监控、定时全量增量生成strm文件。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/thsrite/MoviePilot-Plugins/main/icons/cloudcompanion.png"
    # 插件版本
    plugin_version = "V1.0"
    # 插件作者
    plugin_author = "Felix Yang"
    # 作者主页
    author_url = "https://github.com/luyang1104"
    # 插件配置项ID前缀
    plugin_config_prefix = "cloudstrmHelper_"
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
    _sync_delete = False
    _url = None
    _notify = False
    _refresh_emby = False
    _uriencode = False
    _strm_dir_conf = {}
    _cloud_dir_conf = {}
    _category_conf = {}
    _format_conf = {}
    _cloud_files = []
    _observer = []
    _medias = {}
    _rmt_mediaext = None
    _other_mediaext = None
    _interval: int = 10
    _mediaservers = None
    mediaserver_helper = None
    _emby_paths = {}
    _path_replacements = {}  # 新增：路径替换规则属性
    _cloud_files_json = "cloud_files.json"
    _headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_2_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.192 Safari/537.36",
        "Cookie": "",
    }

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None
    # 退出事件
    _event = threading.Event()
    _state_lock = threading.Lock()
    _event_timers = {}
    _event_timers_lock = threading.Lock()
    _processing_paths = set()
    _generated_files = set()
    _manifest_lock = threading.Lock()
    _manifest_pending = False
    _generated_files_json = "generated_files.json"
    _media_exts = set()
    _other_exts = set()
    _event_delay = 1.0
    _stable_checks = 2
    _stable_interval = 0.5

    _default_rmt_mediaext = ".mp4, .mkv, .ts, .iso,.rmvb, .avi, .mov, .mpeg,.mpg, .wmv, .3gp, .asf, .m4v, .flv, .m2ts, .strm,.tp, .f4v"
    _default_other_mediaext = ".nfo, .jpg, .png, .json"
    _subtitle_exts = {
        ".srt", ".ass", ".ssa", ".sub", ".idx", ".sup", ".vtt",
        ".smi", ".sami", ".ttml", ".dfxp"
    }
    _ignored_dir_names = {"extrafanart", "@recycle", "#recycle", "@eadir"}

    @staticmethod
    def __parse_mapping_line(line: str) -> Optional[Tuple[str, str]]:
        """解析路径映射，优先使用 =>，同时兼容旧版冒号格式。"""
        line = str(line or "").strip()
        if not line:
            return None

        if "=>" in line:
            source, target = line.split("=>", 1)
        else:
            # 兼容 C:\\source:C:\\target 这种 Windows 路径。
            windows_match = re.match(
                r"^(?P<source>[A-Za-z]:[\\/].*?)(?::)(?P<target>.+)$",
                line,
            )
            if windows_match:
                source = windows_match.group("source")
                target = windows_match.group("target")
            elif ":" in line:
                source, target = line.split(":", 1)
            else:
                return None

        source = source.strip()
        target = target.strip()
        if not source or not target:
            return None
        return source, target

    @staticmethod
    def __path_key(path: str) -> str:
        """返回用于边界判断的标准本地路径，不解析软链接。"""
        return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))

    @classmethod
    def __relative_path(cls, path: str, root: str) -> Optional[Path]:
        """获取 path 相对于 root 的路径，path 不在 root 下时返回 None。"""
        # 边界判断使用 normcase，但相对路径必须基于原始路径计算，
        # 否则 Windows 下目标文件名会被意外转换为小写。
        path_value = os.path.abspath(os.path.normpath(str(path)))
        root_value = os.path.abspath(os.path.normpath(str(root)))
        try:
            relative = os.path.relpath(path_value, root_value)
        except ValueError:
            return None
        if relative == os.curdir:
            return Path()
        if relative == os.pardir or relative.startswith(os.pardir + os.sep):
            return None
        return Path(relative)

    @classmethod
    def __is_path_within(cls, path: str, root: str) -> bool:
        return cls.__relative_path(path, root) is not None

    @classmethod
    def __map_path(cls, path: str, source_root: str, target_root: str) -> Optional[str]:
        relative = cls.__relative_path(path, source_root)
        if relative is None:
            return None
        if str(relative) in ("", "."):
            return os.path.normpath(str(target_root))
        return os.path.normpath(os.path.join(str(target_root), str(relative)))

    @staticmethod
    def __normalise_extensions(value: Optional[str], default: str = "") -> set:
        result = set()
        for extension in str(value or default).split(","):
            extension = extension.strip().lower()
            if not extension:
                continue
            if not extension.startswith("."):
                extension = "." + extension
            result.add(extension)
        return result

    def init_plugin(self, config: dict = None):
        # 清空配置
        self.stop_service()
        self._enabled = False
        self._onlyonce = False
        self._interval = 10
        self._monitor = False
        self._cover = False
        self._copy_files = False
        self._copy_subtitles = False
        self._sync_delete = False
        self._refresh_emby = False
        self._notify = False
        self._uriencode = False
        self._monitor_confs = ""
        self._url = ""
        self._mediaservers = []
        self._rmt_mediaext = self._default_rmt_mediaext
        self._other_mediaext = self._default_other_mediaext
        self._strm_dir_conf = {}
        self._cloud_dir_conf = {}
        self._format_conf = {}
        self._category_conf = {}
        self._emby_paths = {}
        self._medias = {}
        self._processing_paths = set()
        self._event_timers = {}
        self._generated_files = set()
        self._manifest_pending = False
        self._path_replacements = {}  # 新增：清空路径替换规则
        self._cloud_files_json = os.path.join(self.get_data_path(), "cloud_files.json")
        self._generated_files_json = os.path.join(self.get_data_path(), "generated_files.json")
        self.mediaserver_helper = MediaServerHelper()
        self.__load_generated_files()

        if config:
            self._enabled = bool(config.get("enabled"))
            self._onlyonce = bool(config.get("onlyonce"))
            self._interval = config.get("interval") or 10
            self._monitor = bool(config.get("monitor"))
            self._cover = bool(config.get("cover"))
            self._copy_files = bool(config.get("copy_files"))
            self._copy_subtitles = bool(config.get("copy_subtitles"))
            self._sync_delete = bool(config.get("sync_delete"))
            self._refresh_emby = bool(config.get("refresh_emby"))
            self._notify = bool(config.get("notify"))
            self._uriencode = bool(config.get("uriencode"))
            self._monitor_confs = config.get("monitor_confs") or ""
            self._url = config.get("url") or ""
            self._mediaservers = config.get("mediaservers") or []
            self._other_mediaext = config.get("other_mediaext") or self._default_other_mediaext
            # 新增：读取路径替换规则
            if config.get("path_replacements"):
                for replacement in str(config.get("path_replacements")).split("\n"):
                    mapping = self.__parse_mapping_line(replacement)
                    if mapping:
                        source, target = mapping
                        self._path_replacements[source] = target
            self._rmt_mediaext = config.get(
                "rmt_mediaext") or self._default_rmt_mediaext
            if config.get("emby_path"):
                for path in str(config.get("emby_path")).split(","):
                    mapping = self.__parse_mapping_line(path)
                    if mapping:
                        source, target = mapping
                        self._emby_paths[source] = target
        else:
            self._monitor_confs = ""
            self._rmt_mediaext = self._default_rmt_mediaext
            self._other_mediaext = self._default_other_mediaext

        self._media_exts = self.__normalise_extensions(self._rmt_mediaext, self._default_rmt_mediaext)
        self._other_exts = self.__normalise_extensions(self._other_mediaext, self._default_other_mediaext)

        if self._enabled or self._onlyonce:
            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)

            if self._notify:
                # 追加入库消息统一发送服务
                self._scheduler.add_job(self.send_msg, trigger='interval', seconds=15)

            # 读取目录配置
            monitor_confs = str(self._monitor_confs or "").splitlines()
            if not monitor_confs:
                return
            for monitor_conf in monitor_confs:
                # 格式 MoviePilot中云盘挂载本地的路径#MoviePilot中strm生成路径#alist/cd2上115路径#strm格式化
                monitor_conf = str(monitor_conf).strip()
                if not monitor_conf:
                    continue
                # 注释
                if str(monitor_conf).startswith("#"):
                    continue

                monitor = None
                if monitor_conf.count("$") == 1:
                    monitor = str(monitor_conf.split("$")[1])
                    monitor_conf = monitor_conf.split("$")[0]
                category = None
                if monitor_conf.count("@") == 1:
                    category = str(monitor_conf.split("@")[1])
                    monitor_conf = monitor_conf.split("@")[0]
                if str(monitor_conf).count("#") >= 3:
                    local_dir, strm_dir, cloud_dir, format_str = monitor_conf.split("#", 3)
                    local_dir = local_dir.strip()
                    strm_dir = strm_dir.strip()
                    cloud_dir = cloud_dir.strip()
                    format_str = format_str.strip()
                else:
                    logger.error(f"{monitor_conf} 格式错误")
                    continue
                # 检查媒体库目录是不是下载目录的子目录
                try:
                    if (strm_dir and (
                            self.__is_path_within(strm_dir, local_dir)
                            or self.__is_path_within(local_dir, strm_dir))):
                        logger.warning(f"{strm_dir} 与 {local_dir} 存在包含关系，无法监控")
                        self.systemmessage.put(f"{strm_dir} 与 {local_dir} 存在包含关系，无法监控")
                        continue
                except Exception as e:
                    logger.debug(str(e))

                if not format_str or not any(token in format_str for token in ("{local_file}", "{cloud_file}")):
                    logger.error(f"{monitor_conf} 格式化模板缺少 {{local_file}} 或 {{cloud_file}}")
                    self.systemmessage.put(f"{local_dir} 格式化模板无效，缺少文件路径占位符")
                    continue

                # 存储目录监控配置
                self._strm_dir_conf[local_dir] = strm_dir
                self._cloud_dir_conf[local_dir] = cloud_dir
                self._format_conf[local_dir] = format_str
                self._category_conf[local_dir] = category

                if not monitor:
                    try:
                        if self._monitor:
                            # 兼容模式，目录同步性能降低且NAS不能休眠，但可以兼容挂载的远程共享目录如SMB
                            observer = PollingObserver(timeout=10)
                            self._observer.append(observer)
                            observer.schedule(FileMonitorHandler(local_dir, self), path=local_dir, recursive=True)
                            observer.daemon = True
                            observer.start()
                            logger.info(f"{local_dir} 的Strm生成实时监控服务启动")
                    except Exception as e:
                        err_msg = str(e)
                        if "inotify" in err_msg and "reached" in err_msg:
                            logger.warning(
                                f"云盘实时监控服务启动出现异常：{err_msg}，请在宿主机上（不是docker容器内）执行以下命令并重启："
                                + """
                                                            echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
                                                            echo fs.inotify.max_user_instances=524288 | sudo tee -a /etc/sysctl.conf
                                                            sudo sysctl -p
                                                            """)
                        else:
                            logger.error(f"{local_dir} 启动x实时监控失败：{err_msg}")
                        self.systemmessage.put(f"{local_dir} 启动实时监控失败：{err_msg}")

            # 运行一次定时服务
            if self._onlyonce:
                logger.info("云盘Strm助手全量执行服务启动，立即运行一次")
                self._scheduler.add_job(func=self.scan, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="云盘Strm助手全量执行服")
                # 关闭一次性开关
                self._onlyonce = False
                # 保存配置
                self.__update_config()

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def scan(self, scan_path: str = None, mon_path: str = None):
        """
        全量执行
        """
        logger.info("开始全量执行")
        monitor_paths = [mon_path] if mon_path else list(self._strm_dir_conf.keys())
        for current_mon_path in monitor_paths:
            if current_mon_path not in self._strm_dir_conf:
                continue
            root_path = scan_path if scan_path and self.__is_path_within(scan_path, current_mon_path) else current_mon_path
            # 遍历目录下所有文件
            for root, dirs, files in os.walk(root_path):
                dirs[:] = [directory for directory in dirs
                           if directory.lower() not in self._ignored_dir_names
                           and not directory.startswith(".")]
                # 处理文件
                for file in files:
                    source_file = os.path.join(root, file)
                    if self.__is_ignored_path(source_file):
                        continue

                    self.__handle_file(event_path=source_file, mon_path=current_mon_path)
        logger.info("全量执行完成")

    @eventmanager.register(EventType.PluginAction)
    def strm_one(self, event: Event = None):
        if event:
            event_data = event.event_data
            if not event_data:
                return
            if event_data.get("action") == "CloudStrmHelper":
                self.scan()
                if event_data.get("user"):
                    self.post_message(channel=event_data.get("channel"),
                                      title="云盘 Strm 全量生成完成！",
                                      userid=event_data.get("user"))
                return
            if event_data.get("action") != "cloudstrm_file":
                return
            file_path = event_data.get("file_path")
            if not file_path:
                logger.error(f"缺少参数：{event_data}")
                return

            # 遍历所有监控目录
            mon_path = self.__find_monitor_path(file_path)

            if not mon_path:
                logger.error(f"未找到文件 {file_path} 对应的监控目录")
                return

            # 处理单文件
            self.__handle_file(event_path=file_path, mon_path=mon_path)

    def __find_monitor_path(self, file_path: str) -> Optional[str]:
        candidates = [
            mon_path for mon_path in self._strm_dir_conf.keys()
            if self.__is_path_within(file_path, mon_path)
        ]
        return max(candidates, key=lambda path: len(self.__path_key(path))) if candidates else None

    @staticmethod
    def __join_remote_path(root: str, relative: Path) -> str:
        root = str(root or "")
        relative_text = str(relative).replace("\\", "/")
        if not relative_text or relative_text == ".":
            return root
        if not root:
            return "/" + relative_text.lstrip("/")
        if root.endswith("/"):
            return root + relative_text
        return root + "/" + relative_text

    def __schedule_file(self, event_path: str, mon_path: str):
        key = (mon_path, self.__path_key(event_path))
        with self._event_timers_lock:
            previous = self._event_timers.pop(key, None)
            if previous:
                previous.cancel()
            timer = threading.Timer(self._event_delay, self.__process_scheduled_file,
                                    args=(event_path, mon_path, key))
            timer.daemon = True
            self._event_timers[key] = timer
            timer.start()

    def __process_scheduled_file(self, event_path: str, mon_path: str, key):
        with self._event_timers_lock:
            self._event_timers.pop(key, None)
        if not self.__wait_for_stable_file(event_path):
            return
        self.__handle_file(event_path=event_path, mon_path=mon_path)

    def __schedule_directory(self, event_path: str, mon_path: str):
        key = ("directory", mon_path, self.__path_key(event_path))
        with self._event_timers_lock:
            previous = self._event_timers.pop(key, None)
            if previous:
                previous.cancel()
            timer = threading.Timer(self._event_delay, self.__process_scheduled_directory,
                                    args=(event_path, mon_path, key))
            timer.daemon = True
            self._event_timers[key] = timer
            timer.start()

    def __process_scheduled_directory(self, event_path: str, mon_path: str, key):
        with self._event_timers_lock:
            self._event_timers.pop(key, None)
        if Path(event_path).is_dir():
            self.scan(scan_path=event_path, mon_path=mon_path)

    def __wait_for_stable_file(self, event_path: str) -> bool:
        """等待挂载文件大小稳定，避免复制到尚未完成的旁车文件。"""
        previous = None
        stable_count = 0
        for _ in range(10):
            try:
                stat = os.stat(event_path)
            except OSError:
                return False
            current = (stat.st_size, getattr(stat, "st_mtime_ns", stat.st_mtime))
            if current == previous:
                stable_count += 1
                if stable_count >= self._stable_checks:
                    return True
            else:
                previous = current
                stable_count = 0
            time.sleep(self._stable_interval)
        logger.warning(f"文件 {event_path} 长时间未稳定，继续尝试同步")
        return Path(event_path).is_file()

    def event_handler(self, event, mon_path: str, text: str, event_path: str,
                      action: str = "created", old_event_path: str = None):
        """
        处理文件变化
        :param event: 事件
        :param mon_path: 监控目录
        :param text: 事件描述
        :param event_path: 事件文件路径
        """
        if '.fuse_hidden' in str(event_path):
            return
        if self.__is_ignored_path(event_path):
            return

        logger.debug(f"监控到文件{text}：{event_path}")
        if action == "deleted":
            if not self._sync_delete:
                return
            # CD2/FUSE 短暂掉线时不要把整个 STRM 媒体库误判为已删除。
            if not Path(mon_path).is_dir():
                logger.warning(f"监控目录 {mon_path} 当前不可访问，跳过删除清理")
                return
            self.__cleanup_source(event_path=event_path, mon_path=mon_path,
                                  is_directory=bool(event.is_directory))
            return

        if action == "moved" and old_event_path and self._sync_delete:
            self.__cleanup_source(event_path=old_event_path, mon_path=mon_path,
                                  is_directory=bool(event.is_directory))

        if event.is_directory:
            if action in {"created", "moved"}:
                self.__schedule_directory(event_path=event_path, mon_path=mon_path)
            return
        self.__schedule_file(event_path=event_path, mon_path=mon_path)

    def __is_ignored_path(self, event_path: str) -> bool:
        path = Path(str(event_path))
        for part in path.parts:
            lower_part = part.lower()
            if lower_part in self._ignored_dir_names or lower_part.startswith("."):
                return True
        return path.name.lower().startswith(".fuse_hidden")

    def __handle_file(self, event_path: str, mon_path: str):
        """
        同步一个文件
        :param event_path: 事件文件路径
        :param mon_path: 监控目录
        """
        source_path = os.path.normpath(str(event_path))
        processing_key = (mon_path, self.__path_key(source_path))
        with self._state_lock:
            if processing_key in self._processing_paths:
                return
            self._processing_paths.add(processing_key)
        try:
            source = Path(source_path)
            if not source.is_file() or self.__is_ignored_path(source_path):
                return

            cloud_dir = self._cloud_dir_conf.get(mon_path)
            strm_dir = self._strm_dir_conf.get(mon_path)
            format_str = self._format_conf.get(mon_path)
            relative = self.__relative_path(source_path, mon_path)
            if relative is None or not strm_dir:
                logger.warning(f"文件 {source_path} 不在监控目录 {mon_path} 内，跳过")
                return

            target_file = self.__map_path(source_path, mon_path, strm_dir)
            cloud_file = self.__join_remote_path(cloud_dir, relative)
            suffix = source.suffix.lower()

            if suffix in self._media_exts:
                strm_content = self.__format_content(
                    format_str=format_str,
                    local_file=source_path,
                    cloud_file=cloud_file,
                    uriencode=self._uriencode,
                )
                if strm_content is None:
                    logger.error(f"{source_path} 未生成 STRM：格式化模板无效")
                    return
                strm_path = os.path.splitext(target_file)[0] + ".strm"
                strm_existed = Path(strm_path).is_file()
                strm_changed = self.__create_strm_file(
                    strm_file=target_file,
                    strm_content=strm_content,
                    source_file=source_path,
                )

                copied = False
                for related_file in self.__find_related_files(source):
                    related_target = self.__map_path(str(related_file), mon_path, strm_dir)
                    if related_target:
                        copied = self.__handle_other_files(
                            event_path=str(related_file), target_file=related_target
                        ) or copied

                if (strm_changed or copied) and self._refresh_emby and self._mediaservers:
                    update_type = "Modified" if strm_existed else "Created"
                    self.__refresh_emby_file(strm_path, update_type=update_type)
            else:
                copied = self.__handle_other_files(event_path=source_path, target_file=target_file)
                if copied and self._refresh_emby and self._mediaservers:
                    self.__refresh_emby_file(
                        self.__related_strm_path(target_file), update_type="Modified"
                    )
        except Exception as e:
            logger.error("目录监控发生错误：%s - %s" % (str(e), traceback.format_exc()))
        finally:
            with self._state_lock:
                self._processing_paths.discard(processing_key)

    def __find_related_files(self, media_file: Path) -> List[Path]:
        related = []
        prefix = media_file.stem
        try:
            entries = media_file.parent.iterdir()
            for file in entries:
                if not file.is_file() or file == media_file:
                    continue
                if file.suffix.lower() in self._media_exts:
                    continue
                if file.name.startswith((prefix + ".", prefix + "-", prefix + "_", prefix + " ")):
                    related.append(file)
        except OSError as err:
            logger.warning(f"读取 {media_file.parent} 旁车文件失败：{err}")
        return related

    def __related_strm_path(self, target_file: str) -> str:
        """将旁车文件路径转换为对应 STRM 路径，找不到时返回原路径。"""
        target = Path(target_file)
        if target.suffix.lower() == ".strm":
            return str(target)
        if target.suffix.lower() in self._media_exts:
            return os.path.splitext(str(target))[0] + ".strm"
        try:
            candidates = [
                file for file in target.parent.glob("*.strm")
                if file.is_file()
                and (target.stem == file.stem
                     or target.stem.startswith((file.stem + ".", file.stem + "-",
                                                 file.stem + "_", file.stem + " ")))
            ]
            if candidates:
                return str(max(candidates, key=lambda file: len(file.stem)))
        except OSError:
            pass
        return str(target)

    def __handle_other_files(self, event_path: str, target_file: str) -> bool:
        """
        处理非媒体文件
        :param event_path: 事件文件路径
        """
        source = Path(event_path)
        suffix = source.suffix.lower()
        should_copy = (
            (self._copy_files and suffix in self._other_exts)
            or (self._copy_subtitles and suffix in self._subtitle_exts)
        )
        if not should_copy or not source.is_file():
            return False
        try:
            target = Path(target_file)
            if self.__path_key(str(source)) == self.__path_key(str(target)):
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file():
                source_stat = source.stat()
                target_stat = target.stat()
                if (source_stat.st_size == target_stat.st_size
                        and source_stat.st_mtime_ns == target_stat.st_mtime_ns):
                    return False
            temp_file = target.with_name(f".{target.name}.tmp")
            with lock:
                shutil.copy2(str(source), str(temp_file))
                os.replace(str(temp_file), str(target))
            self.__mark_generated_file(str(target))
            logger.info(f"复制旁车文件 {source} 到 {target}")
            return True
        except Exception as err:
            logger.error(f"复制旁车文件失败 {source} -> {target_file}：{err}")
            return False

    def __load_generated_files(self):
        try:
            if not Path(self._generated_files_json).is_file():
                return
            with open(self._generated_files_json, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, list):
                self._generated_files = {self.__path_key(path) for path in data if path}
        except (OSError, ValueError) as err:
            logger.warning(f"读取已生成文件清单失败：{err}")

    def __save_generated_files(self):
        with self._manifest_lock:
            try:
                path = Path(self._generated_files_json)
                path.parent.mkdir(parents=True, exist_ok=True)
                with self._state_lock:
                    generated_files = sorted(self._generated_files)
                temp_file = path.with_name(f".{path.name}.tmp")
                with open(temp_file, "w", encoding="utf-8") as file:
                    json.dump(generated_files, file, ensure_ascii=False, indent=2)
                os.replace(str(temp_file), str(path))
            except OSError as err:
                logger.warning(f"保存已生成文件清单失败：{err}")

    def __mark_generated_file(self, path: str):
        path_key = self.__path_key(path)
        with self._state_lock:
            if path_key in self._generated_files:
                return
            self._generated_files.add(path_key)
            self._manifest_pending = True

        key = ("generated-files-manifest",)
        with self._event_timers_lock:
            previous = self._event_timers.pop(key, None)
            if previous:
                previous.cancel()
            timer = threading.Timer(2.0, self.__flush_generated_files, args=(key,))
            timer.daemon = True
            self._event_timers[key] = timer
            timer.start()

    def __flush_generated_files(self, key=("generated-files-manifest",)):
        with self._event_timers_lock:
            self._event_timers.pop(key, None)
        with self._state_lock:
            pending = self._manifest_pending
            self._manifest_pending = False
        if pending:
            self.__save_generated_files()

    def __remove_file_if_generated(self, path: str):
        path_key = self.__path_key(path)
        with self._state_lock:
            was_generated = path_key in self._generated_files
        if not was_generated:
            return False
        try:
            target = Path(path)
            if target.is_file():
                target.unlink()
            with self._state_lock:
                self._generated_files.discard(path_key)
            logger.info(f"清理已生成文件 {target}")
            return True
        except OSError as err:
            logger.warning(f"清理已生成文件失败 {path}：{err}")
            return False

    def __cleanup_source(self, event_path: str, mon_path: str, is_directory: bool = False):
        """按源路径清理 STRM 及插件复制的旁车文件。"""
        strm_dir = self._strm_dir_conf.get(mon_path)
        if not strm_dir:
            return
        relative = self.__relative_path(event_path, mon_path)
        if relative is None:
            return
        target = Path(self.__map_path(event_path, mon_path, strm_dir))
        candidates = []
        if is_directory:
            root = target
            if root.exists():
                candidates = [path for path in root.rglob("*") if path.is_file()]
            else:
                prefix = self.__path_key(str(root)) + os.sep
                with self._state_lock:
                    generated_files = list(self._generated_files)
                candidates = [path for path_key in generated_files
                              if path_key.startswith(prefix) for path in [Path(path_key)]]
        else:
            if Path(event_path).suffix.lower() in self._media_exts:
                candidates.append(Path(os.path.splitext(str(target))[0] + ".strm"))
                try:
                    candidates.extend(
                        file for file in target.parent.iterdir()
                        if file.is_file()
                        and (file.name.startswith(target.stem + ".")
                             or file.name.startswith(target.stem + "-")
                             or file.name.startswith(target.stem + "_")
                             or file.name.startswith(target.stem + " "))
                    )
                except OSError:
                    pass
            if target.suffix.lower() in self._subtitle_exts or target.suffix.lower() in self._other_exts:
                candidates.append(target)
        removed = False
        for candidate in candidates:
            removed = self.__remove_file_if_generated(str(candidate)) or removed
        if removed:
            with self._state_lock:
                self._manifest_pending = False
            self.__save_generated_files()
            if self._refresh_emby and self._mediaservers:
                refresh_path = str(target)
                if Path(event_path).suffix.lower() in self._media_exts:
                    refresh_path = os.path.splitext(refresh_path)[0] + ".strm"
                elif not is_directory:
                    refresh_path = self.__related_strm_path(refresh_path)
                self.__refresh_emby_file(refresh_path, update_type="Deleted")

    def __sava_json(self):
        """
        保存json文件
        """
        logger.info(f"开始写入本地文件 {self._cloud_files_json}")
        file = open(self._cloud_files_json, 'w')
        file.write(json.dumps(self._cloud_files))
        file.close()

    @staticmethod
    def __format_content(format_str: str, local_file: str, cloud_file: str, uriencode: bool):
        """
        格式化strm内容
        """
        format_str = str(format_str or "")
        if "{cloud_file}" in format_str:
            if uriencode:
                # 对盘符之后的所有内容进行url转码
                cloud_file = urllib.parse.quote(cloud_file, safe='')
            else:
                # 替换路径中的\为/
                cloud_file = cloud_file.replace("\\", "/")
            format_str = format_str.replace("{cloud_file}", cloud_file)
        if "{local_file}" in format_str:
            format_str = format_str.replace("{local_file}", local_file)
        if "{local_file}" in format_str or "{cloud_file}" in format_str:
            return None
        return format_str

    def __create_strm_file(self, strm_file: str, strm_content: str, source_file: str = None) -> bool:

        """
        生成strm文件
        :param library_dir:
        :param dest_dir:
        :param dest_file:
        """
        try:
            # 文件
            if not Path(strm_file).parent.exists():
                logger.info(f"创建目标文件夹 {Path(strm_file).parent}")
                os.makedirs(Path(strm_file).parent, exist_ok=True)

            # 构造.strm文件路径
            strm_file = os.path.join(Path(strm_file).parent, f"{os.path.splitext(Path(strm_file).name)[0]}.strm")

            # 媒体文件
            if Path(strm_file).exists() and not self._cover:
                logger.info(f"目标文件 {strm_file} 已存在")
                return False
            # 新增：应用自定义路径替换规则
            for source, target in self._path_replacements.items():
                if source in strm_content:
                    strm_content = strm_content.replace(source, target)
                    logger.debug(f"应用路径替换规则: {source} -> {target}")

            # 原子写入，避免媒体服务器读到半截 STRM。
            temp_file = Path(strm_file).with_name(f".{Path(strm_file).name}.tmp")
            with open(temp_file, 'w', encoding='utf-8', newline="") as f:
                f.write(strm_content)
            os.replace(str(temp_file), strm_file)
            self.__mark_generated_file(strm_file)

            logger.info(f"创建strm文件成功 {strm_file} -> {strm_content}")
            if self._url and source_file and Path(source_file).suffix.lower() in self._media_exts:
                try:
                    RequestUtils(content_type="application/json").post(
                        url=self._url,
                        json={"path": str(strm_content), "type": "add"},
                    )
                except Exception as err:
                    logger.warning(f"STRM 任务推送失败 {strm_file}：{err}")

            if self._notify and source_file and Path(source_file).suffix.lower() in self._media_exts:
                # 发送消息汇总
                file_meta = MetaInfoPath(Path(strm_file))

                pattern = r'tmdbid=(\d+)'
                # 提取 tmdbid
                match = re.search(pattern, strm_file)
                if match:
                    tmdbid = match.group(1)
                    file_meta.tmdbid = tmdbid

                key = f"{file_meta.cn_name} ({file_meta.year}){f' {file_meta.season}' if file_meta.season else ''}"
                with self._state_lock:
                    media_list = self._medias.get(key) or {}
                    episodes = media_list.get("episodes") or []
                    if file_meta.begin_episode:
                        if int(file_meta.begin_episode) not in episodes:
                            episodes.append(int(file_meta.begin_episode))
                    self._medias[key] = {
                        "episodes": episodes,
                        "file_meta": file_meta,
                        "type": "tv" if file_meta.season else "movie",
                        "time": datetime.now()
                    }

            return True
        except Exception as e:
            logger.error(f"创建strm文件失败 {strm_file} -> {str(e)}")
        return False

    def __refresh_emby_file(self, strm_file: str, update_type: str = "Created"):
        """
        通知emby刷新文件
        """
        emby_servers = self.mediaserver_helper.get_services(name_filters=self._mediaservers, type_filter="emby")
        if not emby_servers:
            logger.error("未配置Emby媒体服务器")
            return

        strm_file = self.__get_path(paths=self._emby_paths, file_path=strm_file)
        success = True
        for emby_name, emby_server in emby_servers.items():
            emby = emby_server.instance

            logger.info(f"开始通知媒体服务器 {emby_name} 刷新增量文件 {strm_file}")
            try:
                res = emby.post_data(
                    url=f'[HOST]emby/Library/Media/Updated?api_key=[APIKEY]&reqformat=json',
                    data=json.dumps({
                        "Updates": [
                            {
                                "Path": strm_file,
                                "UpdateType": update_type,
                            }
                        ]
                    }),
                    headers={
                        "Content-Type": "application/json"
                    }
                )
                if res and res.status_code in [200, 204]:
                    logger.info(f"媒体服务器 {emby_name} 已刷新 {strm_file}")
                else:
                    status_code = res.status_code if res else "无响应"
                    logger.error(f"通知媒体服务器 {emby_name} 刷新文件 {strm_file} 失败，错误码：{status_code}")
                    success = False
            except Exception as err:
                logger.error(f"通知媒体服务器刷新新增文件失败：{str(err)}")
                success = False
        return success

    def __get_path(self, paths, file_path: str):
        """
        路径转换
        """
        if paths:
            matches = [path for path in paths.keys()
                       if self.__is_path_within(file_path, path)]
            if matches:
                library_path = max(matches, key=lambda path: len(self.__path_key(path)))
                relative = self.__relative_path(file_path, library_path)
                target_root = str(paths.get(library_path) or "")
                if relative is not None:
                    relative_text = str(relative)
                    if target_root.startswith("/"):
                        return target_root.rstrip("/") + "/" + relative_text.replace("\\", "/")
                    return os.path.normpath(os.path.join(target_root, relative_text))
        # 未匹配到路径，返回原路径
        return file_path

    def export_dir(self, fid, destination_id="0"):
        """
        获取目录导出id
        """
        export_api = "https://webapi.115.com/files/export_dir"
        response = requests.post(url=export_api,
                                 headers=self._headers,
                                 data={"file_ids": fid, "target": f"U_1_{destination_id}"})
        if response.status_code == 200:
            result = response.json()
            if result.get("state"):
                export_id = result.get("data", {}).get("export_id")

                retry_cnt = 60
                while retry_cnt > 0:
                    response = requests.get(url=export_api,
                                            headers=self._headers,
                                            data={"export_id": export_id})
                    if response.status_code == 200:
                        result = response.json()
                        if result.get("state"):
                            if str(export_id) == str(result.get("data", {}).get("export_id")):
                                return result.get("data", {}).get("pick_code"), result.get("data", {}).get("file_id")
                    retry_cnt -= 1
                    logger.info(f"等待目录树生成完成，剩余重试 {retry_cnt} 次")
                    time.sleep(3)
        return None

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
                    mon_path = None
                    mon_path = self.__find_monitor_path(category)

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
                        if mon_category and str(category) in mon_category:
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
                mon_path = None
                mon_path = self.__find_monitor_path(args)

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
                        if mon_category and str(args) in mon_category:
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
        """
        定时检查是否有媒体处理完，发送统一消息
        """
        if not self._medias or not self._medias.keys():
            return

        # 遍历检查是否已刮削完，发送消息
        with self._state_lock:
            pending_medias = list(self._medias.items())
        for medis_title_year_season, media_list in pending_medias:
            logger.info(f"开始处理媒体 {medis_title_year_season} 消息")

            if not media_list:
                continue

            # 获取最后更新时间
            last_update_time = media_list.get("time")
            file_meta = media_list.get("file_meta")
            mtype = media_list.get("type")
            episodes = media_list.get("episodes")
            if not last_update_time:
                continue

            # 判断剧集最后更新时间距现在是已超过10秒或者电影，发送消息
            if (datetime.now() - last_update_time).total_seconds() > int(self._interval) \
                    or str(mtype) == "movie":
                # 发送通知
                if self._notify:
                    file_count = len(episodes) if episodes else 1

                    # 剧集季集信息 S01 E01-E04 || S01 E01、E02、E04
                    # 处理文件多，说明是剧集，显示季入库消息
                    media_type = None
                    if str(mtype) == "tv":
                        # 季集文本
                        season_episode = f"{medis_title_year_season} {StringUtils.format_ep(episodes)}"
                        media_type = MediaType.TV
                    else:
                        # 电影文本
                        season_episode = f"{medis_title_year_season}"
                        media_type = MediaType.MOVIE

                    # 获取封面图片
                    mediainfo: MediaInfo = self.chain.recognize_media(meta=file_meta,
                                                                      mtype=media_type,
                                                                      tmdbid=file_meta.tmdbid)

                    # 发送消息
                    self.send_transfer_message(msg_title=season_episode,
                                               file_count=file_count,
                                               image=(
                                                   mediainfo.backdrop_path if mediainfo.backdrop_path else mediainfo.poster_path) if mediainfo else None)
                # 发送完消息，移出 key；期间若有新文件更新则保留新记录。
                with self._state_lock:
                    if self._medias.get(medis_title_year_season) is media_list:
                        self._medias.pop(medis_title_year_season, None)
                continue

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
        更新配置
        """
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cover": self._cover,
            "notify": self._notify,
            "monitor": self._monitor,
            "interval": self._interval,
            "copy_files": self._copy_files,
            "copy_subtitles": self._copy_subtitles,
            "sync_delete": self._sync_delete,
            "refresh_emby": self._refresh_emby,
            "uriencode": self._uriencode,
            "url": self._url,
            "monitor_confs": self._monitor_confs,
            "rmt_mediaext": self._rmt_mediaext,
            "other_mediaext": self._other_mediaext,
            "mediaservers": self._mediaservers,
            "emby_path": ",".join([f"{source}=>{target}" for source, target in self._emby_paths.items()]),
            # 新增：路径替换规则
            "path_replacements": "\n".join([f"{source}=>{target}" for source, target in
                                            self._path_replacements.items()]) if self._path_replacements else "",
        })

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [
            {
                "cmd": "/cloud_strm_companion",
                "event": EventType.PluginAction,
                "desc": "云盘Strm助手同步",
                "category": "",
                "data": {
                    "action": "CloudStrmHelper"
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

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'text': '云盘实时监控任何问题不予处理，请自行消化。'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'monitor',
                                            'label': '实时监控',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'copy_files',
                                            'label': '复制非媒体文件',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'cover',
                                            'label': '覆盖已存在文件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'uriencode',
                                            'label': 'url编码',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'sync_delete',
                                            'label': '同步删除（谨慎开启）',
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'refresh_emby',
                                            'label': '刷新媒体库（Emby）',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'copy_subtitles',
                                            'label': '复制字幕文件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'interval',
                                            'label': '消息延迟',
                                            'placeholder': '10'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'monitor_confs',
                                            'label': '目录配置',
                                            'rows': 5,
                                            'placeholder': 'MoviePilot中云盘挂载本地的路径#MoviePilot中strm生成路径#alist/cd2上115路径#strm格式化'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'rmt_mediaext',
                                            'label': '视频格式',
                                            'rows': 2,
                                            'placeholder': ".mp4, .mkv, .ts, .iso,.rmvb, .avi, .mov, .mpeg,.mpg, .wmv, .3gp, .asf, .m4v, .flv, .m2ts, .strm,.tp, .f4v"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'other_mediaext',
                                            'label': '非媒体文件格式',
                                            'rows': 2,
                                            'placeholder': ".nfo, .jpg"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'mediaservers',
                                            'label': '媒体服务器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in self.mediaserver_helper.get_configs().values() if
                                                      config.type == "emby"]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 8
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'emby_path',
                                            'rows': '1',
                                            'label': '媒体库路径映射',
                                            'placeholder': 'MoviePilot本地文件路径:Emby文件路径（多组路径英文逗号拼接）'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 新增：路径替换规则文本框
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'path_replacements',
                                            'label': '路径替换规则',
                                            'rows': 3,
                                            'placeholder': '源路径:目标路径（每行一条规则）'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': 'MoviePilot中云盘挂载本地的路径：/mnt/media/series/国产剧/雪迷宫 (2024)；'
                                                    'MoviePilot中strm生成路径：/mnt/library/series/国产剧/雪迷宫 (2024)；'
                                                    '云盘路径：/cloud/media/series/国产剧/雪迷宫 (2024)；'
                                                    '则目录配置为：/mnt/media#/mnt/library#/cloud/media#{local_file}'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': 'strm格式化方式，自行把()替换为alist/cd2上路径：'
                                                    '1.本地源文件路径：{local_file}。'
                                                    '2.alist路径：http://192.168.31.103:5244/d/115{cloud_file}。'
                                                    '3.cd2路径：http://192.168.31.103:19798/static/http/192.168.31.103:19798/False/115{cloud_file}。'
                                                    '4.其他api路径：http://192.168.31.103:2001/{cloud_file}'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "url",
                                            "label": "任务推送url",
                                            "placeholder": "post请求json方式推送path和type(add)字段",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ]
            }
        ], {
            "enabled": False,
            "notify": False,
            "monitor": False,
            "cover": False,
            "onlyonce": False,
            "copy_files": False,
            "uriencode": False,
            "copy_subtitles": False,
            "sync_delete": False,
            "refresh_emby": False,
            "mediaservers": [],
            "monitor_confs": "",
            "emby_path": "",
            "interval": 10,
            "url": "",
            "other_mediaext": ".nfo, .jpg, .png, .json",
            "rmt_mediaext": ".mp4, .mkv, .ts, .iso,.rmvb, .avi, .mov, .mpeg,.mpg, .wmv, .3gp, .asf, .m4v, .flv, .m2ts, .strm,.tp, .f4v",
            "path_replacements": ""  # 新增：路径替换规则默认值
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        if self._observer:
            for observer in self._observer:
                try:
                    observer.stop()
                    observer.join()
                except Exception as e:
                    logger.warning(f"停止目录监控失败：{e}")
        self._observer = []
        with self._event_timers_lock:
            timers = list(self._event_timers.values())
            self._event_timers.clear()
        for timer in timers:
            try:
                timer.cancel()
            except Exception:
                pass
        with self._state_lock:
            manifest_pending = self._manifest_pending
            self._manifest_pending = False
        if manifest_pending:
            self.__save_generated_files()
        if self._scheduler:
            self._scheduler.remove_all_jobs()
            if self._scheduler.running:
                self._event.set()
                self._scheduler.shutdown()
                self._event.clear()
            self._scheduler = None
