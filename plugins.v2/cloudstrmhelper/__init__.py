import json
import os
import re
import shutil
import threading
import time
import traceback
import urllib.parse
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Body
from fastapi.responses import JSONResponse
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
    plugin_version = "V1.1"
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
    _task_history_limit = 30
    _task_history = []
    _task_history_json = "task_history.json"
    _task_history_lock = threading.RLock()
    _task_active_id = None
    _task_stop_event = threading.Event()
    _task_context = threading.local()
    _task_thread = None
    _task_thread_task_id = None
    _task_thread_lock = threading.Lock()
    _task_stop_events = {}
    _task_generations = {}
    _task_generation = 0
    _page_filter_status = None
    _page_task_id = None
    _task_selected_items = {}
    _task_history_dirty = 0
    _task_history_last_saved = 0.0
    _task_history_save_interval = 0.5
    _task_history_save_batch = 20
    _config_errors = []

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

    def __validate_monitor_confs(self, monitor_confs: str) -> List[str]:
        """Validate directory configuration without starting monitors or scheduling work."""
        errors = []
        for original_conf in str(monitor_confs or "").splitlines():
            monitor_conf = original_conf.strip()
            if not monitor_conf or monitor_conf.startswith("#"):
                continue
            if monitor_conf.count("$") == 1:
                monitor_conf = monitor_conf.split("$", 1)[0]
            if monitor_conf.count("@") == 1:
                monitor_conf = monitor_conf.split("@", 1)[0]
            if monitor_conf.count("#") < 3:
                errors.append(f"目录配置格式错误：{original_conf.strip()}")
                continue
            local_dir, strm_dir, _cloud_dir, format_str = monitor_conf.split("#", 3)
            local_dir = local_dir.strip()
            strm_dir = strm_dir.strip()
            format_str = format_str.strip()
            if not local_dir or not strm_dir:
                errors.append(f"目录配置格式错误：{original_conf.strip()}")
                continue
            try:
                if (self.__is_path_within(strm_dir, local_dir)
                        or self.__is_path_within(local_dir, strm_dir)):
                    errors.append(f"目录配置存在包含关系：{local_dir} 与 {strm_dir}")
                    continue
            except Exception:
                errors.append(f"目录配置路径无效：{original_conf.strip()}")
                continue
            if not any(token in format_str for token in ("{local_file}", "{cloud_file}")):
                errors.append(f"{local_dir} 格式化模板缺少 {{local_file}} 或 {{cloud_file}}")
        return errors

    @staticmethod
    def __task_now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def __task_result(source_file: str, target_file: str = "", status: str = "skipped",
                      action: str = "", stage: str = "", reason: str = "",
                      retryable: bool = False, monitor_path: str = "") -> dict:
        return {
            "id": uuid.uuid4().hex[:12],
            "source_file": str(source_file or ""),
            "target_file": str(target_file or ""),
            "action": action,
            "status": status,
            "stage": stage,
            "reason": reason,
            "retryable": bool(retryable),
            "monitor_path": str(monitor_path or ""),
            "created_at": CloudStrmHelper.__task_now(),
        }

    def __save_task_history(self, force: bool = False):
        """节流保存任务历史，同时保持临时文件替换的原子性。"""
        with self._task_history_lock:
            elapsed = time.monotonic() - self._task_history_last_saved
            if (not force and self._task_history_dirty < self._task_history_save_batch
                    and elapsed < self._task_history_save_interval):
                return
            snapshot = deepcopy(self._task_history)
            path = Path(self._task_history_json)
            temp_file = path.with_name(f".{path.name}.tmp")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(temp_file, "w", encoding="utf-8") as file:
                    json.dump(snapshot, file, ensure_ascii=False, indent=2)
                os.replace(str(temp_file), str(path))
                self._task_history_dirty = 0
                self._task_history_last_saved = time.monotonic()
            except OSError as err:
                try:
                    if temp_file.exists():
                        temp_file.unlink()
                except OSError:
                    pass
                logger.warning(f"保存任务历史失败：{err}")

    def __load_task_history(self):
        changed = False
        try:
            path = Path(self._task_history_json)
            if path.is_file():
                with open(path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                if isinstance(data, list):
                    self._task_history = [item for item in data if isinstance(item, dict)][-self._task_history_limit:]
        except (OSError, ValueError) as err:
            logger.warning(f"读取任务历史失败：{err}")
            self._task_history = []

        now = self.__task_now()
        with self._task_history_lock:
            for task in self._task_history:
                if not isinstance(task, dict):
                    continue
                if task.get("status") == "running":
                    task["status"] = "interrupted"
                    task["finished_at"] = now
                    task["error"] = "插件重启时任务未完成"
                    task["duration_seconds"] = self.__task_duration(task)
                    changed = True
            running = next((task for task in reversed(self._task_history)
                            if task.get("status") == "running"), None)
            self._task_active_id = running.get("id") if running else None
        if changed:
            try:
                self.__save_task_history(force=True)
            except OSError as err:
                logger.warning(f"保存中断任务历史失败：{err}")

    def __task_snapshot(self, task: dict, include_items: bool = True) -> dict:
        snapshot = deepcopy(task)
        if not include_items:
            snapshot.pop("items", None)
        return snapshot

    def __trim_task_history(self):
        with self._task_history_lock:
            ended = [item for item in self._task_history if item.get("status") != "running"]
            running = [item for item in self._task_history if item.get("status") == "running"]
            self._task_history = ended[-self._task_history_limit:] + running

    def __task_summary(self, task: dict) -> dict:
        summary = self.__task_snapshot(task, include_items=False)
        summary["duration_seconds"] = self.__task_duration(summary)
        return summary

    def __current_task(self) -> Optional[dict]:
        with self._task_history_lock:
            for task in reversed(self._task_history):
                if task.get("status") == "running":
                    return self.__task_summary(task)
        return None

    def __create_task(self, kind: str, scope: dict) -> Tuple[Optional[dict], Optional[dict]]:
        with self._task_history_lock:
            active = next((task for task in reversed(self._task_history)
                           if task.get("status") == "running"), None)
            if active:
                self._task_active_id = active.get("id")
                return None, self.__task_summary(active)
            if self._task_thread and self._task_thread.is_alive():
                stopping_id = self._task_thread_task_id or self._task_active_id
                stopping = next((task for task in reversed(self._task_history)
                                 if task.get("id") == stopping_id), None)
                if stopping:
                    return None, self.__task_summary(stopping)
                return None, {"id": stopping_id, "status": "running"}

            now = self.__task_now()
            task = {
                "id": uuid.uuid4().hex[:12],
                "kind": kind,
                "status": "running",
                "created_at": now,
                "started_at": now,
                "finished_at": None,
                "updated_at": now,
                "scope": scope or {},
                "stats": {
                    "discovered": 0,
                    "processed": 0,
                    "success": 0,
                    "skipped": 0,
                    "failed": 0,
                },
                "items": [],
            }
            self._task_history.append(task)
            self._task_active_id = task["id"]
            self._task_stop_event.clear()
            self._task_stop_events[task["id"]] = threading.Event()
            self._task_generations[task["id"]] = self._task_generation
            self._task_history_dirty += 1
            self.__save_task_history(force=True)
            return self.__task_snapshot(task), None

    def __task_discover(self, task_id: str):
        with self._task_history_lock:
            task = next((item for item in self._task_history if item.get("id") == task_id), None)
            if not task or task.get("status") != "running":
                return
            task["stats"]["discovered"] += 1
            task["updated_at"] = self.__task_now()
            self._task_history_dirty += 1
        self.__save_task_history()

    def __task_record_result(self, task_id: str, result: dict):
        result = deepcopy(result or {})
        result.setdefault("id", uuid.uuid4().hex[:12])
        result.setdefault("status", "failed")
        result.setdefault("created_at", self.__task_now())
        with self._task_history_lock:
            task = next((item for item in self._task_history if item.get("id") == task_id), None)
            if not task or task.get("status") != "running":
                return
            duplicate = next((item for item in task["items"]
                              if item.get("source_file") == result.get("source_file")
                              and item.get("target_file") == result.get("target_file")
                              and item.get("action") == result.get("action")
                              and item.get("stage") == result.get("stage")), None)
            if duplicate:
                return
            task["items"].append(result)
            task["stats"]["processed"] += 1
            status = result.get("status")
            if status not in {"success", "skipped", "failed"}:
                status = "failed"
                result["status"] = status
            task["stats"].setdefault(status, 0)
            task["stats"][status] += 1
            task["updated_at"] = self.__task_now()
            self._task_history_dirty += 1
        self.__save_task_history()

    def __task_is_stopped(self, task_id: str) -> bool:
        # Each worker keeps its own event so a plugin reload cannot clear the
        # stop signal before the old daemon thread has exited.
        event = getattr(self._task_context, "stop_event", None)
        if event is None:
            event = self._task_stop_events.get(task_id)
        generation = getattr(self._task_context, "task_generation", None)
        if generation is not None and generation != self._task_generation:
            return True
        return bool(event and event.is_set())

    def __task_claim_source(self, task_id: str, source_file: str) -> bool:
        if not task_id:
            return True
        seen_sources = getattr(self._task_context, "seen_sources", None)
        if seen_sources is None:
            seen_sources = set()
            self._task_context.seen_sources = seen_sources
        source_key = self.__path_key(source_file)
        if source_key in seen_sources:
            return False
        seen_sources.add(source_key)
        return True

    def __task_claim_sidecar(self, source_file: str) -> bool:
        handled_sidecars = getattr(self._task_context, "handled_sidecars", None)
        if handled_sidecars is None:
            handled_sidecars = set()
            self._task_context.handled_sidecars = handled_sidecars
        source_key = self.__path_key(source_file)
        if source_key in handled_sidecars:
            return False
        handled_sidecars.add(source_key)
        return True

    def __finish_task(self, task_id: str, error: str = "", channel=None, userid=None):
        with self._task_history_lock:
            task = next((item for item in self._task_history if item.get("id") == task_id), None)
            if not task or task.get("status") != "running":
                return
            stats = task.get("stats") or {}
            if error:
                if not any(item.get("action") == "task" for item in task.get("items") or []):
                    failure = self.__task_result("", status="failed", action="task",
                                                  stage="execution", reason=error, retryable=False)
                    task.setdefault("items", []).append(failure)
                    stats["processed"] = stats.get("processed", 0) + 1
                    stats["failed"] = stats.get("failed", 0) + 1
                status = ("partial" if stats.get("failed", 0)
                          and stats.get("success", 0) + stats.get("skipped", 0)
                          else "failed")
                task["error"] = error
            elif self.__task_is_stopped(task_id):
                status = "interrupted"
                task["error"] = "任务被插件停止"
            elif stats.get("failed", 0) and stats.get("success", 0) + stats.get("skipped", 0):
                status = "partial"
            elif stats.get("failed", 0):
                status = "failed"
            else:
                status = "success"
            task["status"] = status
            task["finished_at"] = self.__task_now()
            task["updated_at"] = task["finished_at"]
            try:
                started = datetime.fromisoformat(str(task.get("started_at")))
                finished = datetime.fromisoformat(str(task["finished_at"]))
                task["duration_seconds"] = max(0.0, round((finished - started).total_seconds(), 3))
            except (TypeError, ValueError):
                task["duration_seconds"] = None
            if self._task_active_id == task_id:
                self._task_active_id = None
            self._task_stop_events.pop(task_id, None)
            self._task_generations.pop(task_id, None)
            self._task_history_dirty += 1
            finished = self.__task_snapshot(task)
            ended = [item for item in self._task_history if item.get("status") != "running"]
            self._task_history = ended[-self._task_history_limit:] + [
                item for item in self._task_history if item.get("status") == "running"
            ]
        self.__save_task_history(force=True)
        self.__notify_task(finished, channel=channel, userid=userid)

    def __run_task(self, task_id: str, worker, channel=None, userid=None, generation=None):
        stop_event = self._task_stop_events.get(task_id)
        try:
            self._task_context.task_id = task_id
            self._task_context.stop_event = stop_event
            self._task_context.task_generation = generation
            self._task_context.seen_sources = set()
            self._task_context.allowed_sources = None
            self._task_context.handled_sidecars = set()
            worker(task_id)
        except Exception as err:
            logger.error(f"CloudStrm 任务执行失败：{err} - {traceback.format_exc()}")
            self.__finish_task(task_id, error=str(err), channel=channel, userid=userid)
        else:
            self.__finish_task(task_id, channel=channel, userid=userid)
        finally:
            self._task_context.task_id = None
            self._task_context.stop_event = None
            self._task_context.task_generation = None
            self._task_context.seen_sources = None
            self._task_context.allowed_sources = None
            self._task_context.handled_sidecars = None
            with self._task_history_lock:
                if self._task_stop_events.get(task_id) is stop_event:
                    self._task_stop_events.pop(task_id, None)
                if self._task_thread is threading.current_thread():
                    self._task_thread = None
                    self._task_thread_task_id = None
                if self._task_active_id == task_id:
                    self._task_active_id = None

    def __start_task(self, kind: str, scope: dict, worker, channel=None, userid=None) -> dict:
        with self._task_thread_lock:
            task, active = self.__create_task(kind, scope)
            if active:
                return {"accepted": False, "task_id": active.get("id"), "task": active,
                        "message": "已有任务正在运行"}
            thread = threading.Thread(
                target=self.__run_task,
                args=(task["id"], worker, channel, userid,
                      self._task_generations.get(task["id"], self._task_generation)),
                name=f"cloudstrm-task-{task['id']}", daemon=True,
            )
            self._task_thread = thread
            self._task_thread_task_id = task["id"]
            thread.start()
        return {"accepted": True, "task_id": task["id"], "task": task}

    def __get_task(self, task_id: str) -> Optional[dict]:
        with self._task_history_lock:
            task = next((item for item in self._task_history if item.get("id") == task_id), None)
            return self.__task_snapshot(task) if task else None

    def __task_page_link(self) -> str:
        return settings.MP_DOMAIN(f"#/plugins?tab=installed&id={self.__class__.__name__}")

    def __notify_task(self, task: dict, channel=None, userid=None):
        if not self._notify or not task:
            return
        stats = task.get("stats") or {}
        scope = task.get("scope") or {}
        kind_names = {"full_scan": "全量扫描", "targeted": "定向同步", "retry": "失败重试"}
        title = f"CloudStrm 任务完成：成功 {stats.get('success', 0)}，跳过 {stats.get('skipped', 0)}，失败 {stats.get('failed', 0)}"
        text = (
            f"类型：{kind_names.get(task.get('kind'), task.get('kind', '任务'))}\n"
            f"范围：{scope.get('path') or '全部监控目录'}\n"
            f"总数：{stats.get('discovered', 0)}，已处理：{stats.get('processed', 0)}\n"
            f"任务状态：{task.get('status')}\n"
            f"失败项：{stats.get('failed', 0)}\n"
            f"总耗时：{self.__task_duration(task) or 0:.1f} 秒"
        )
        message = {"mtype": NotificationType.Plugin, "title": title, "text": text,
                   "link": self.__task_page_link()}
        if channel:
            message["channel"] = channel
        if userid:
            message["userid"] = userid
        try:
            self.post_message(**message)
        except Exception as err:
            logger.warning(f"发送 CloudStrm 任务摘要通知失败：{err}")

    def __api_error(self, status_code: int, message: str, **extra) -> JSONResponse:
        payload = {"error": message, "message": message}
        payload.update(extra)
        return JSONResponse(status_code=status_code, content=payload)

    @staticmethod
    def __task_duration(task: dict) -> Optional[float]:
        if task.get("duration_seconds") is not None:
            return task.get("duration_seconds")
        try:
            started = datetime.fromisoformat(str(task.get("started_at")))
            end_value = task.get("finished_at") or datetime.now().isoformat(timespec="seconds")
            finished = datetime.fromisoformat(str(end_value))
            return max(0.0, round((finished - started).total_seconds(), 3))
        except (TypeError, ValueError):
            return None

    def __api_tasks(self, status: str = None):
        summaries = []
        with self._task_history_lock:
            tasks = list(reversed(self._task_history))
            if status:
                tasks = [task for task in tasks if task.get("status") == status]
            summaries = [self.__task_summary(task) for task in tasks[:self._task_history_limit]]
        current = self.__current_task()
        if status and current and current.get("status") != status:
            current = None
        return {"current": current, "tasks": summaries, "total": len(summaries)}

    def __api_task_detail(self, task_id: str, status: str = None, page: int = 1,
                          page_size: int = 50):
        task = self.__get_task(task_id)
        if not task:
            return self.__api_error(404, f"任务不存在：{task_id}")
        try:
            page = max(1, int(page))
            page_size = min(200, max(1, int(page_size)))
        except (TypeError, ValueError):
            return self.__api_error(400, "page 和 page_size 必须是数字")
        items = task.get("items") or []
        if status:
            if status not in {"success", "skipped", "failed"}:
                return self.__api_error(400, "明细状态只能是 success、skipped 或 failed")
            items = [item for item in items if item.get("status") == status]
        total = len(items)
        start = (page - 1) * page_size
        detail = self.__task_snapshot(task)
        detail["items"] = deepcopy(items[start:start + page_size])
        detail["pagination"] = {
            "page": page, "page_size": page_size, "total": total,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }
        detail["duration_seconds"] = self.__task_duration(detail)
        return detail

    def __api_start_task(self, payload: Optional[dict] = Body(default=None)):
        payload = payload or {}
        kind = str(payload.get("kind") or payload.get("mode") or "full_scan").strip()
        if kind not in {"full_scan", "targeted"}:
            return self.__api_error(400, "任务模式只能是 full_scan 或 targeted")
        path = str(payload.get("path") or "").strip()
        mon_path = self.__find_monitor_path(path) if path else None
        if path:
            path_obj = Path(path)
            if not path_obj.exists():
                return self.__api_error(400, "目标路径不存在")
            if not mon_path or not self.__is_path_within(path, mon_path):
                return self.__api_error(400, "目标路径不属于已配置的监控目录")
            if kind == "full_scan" and not path_obj.is_dir():
                return self.__api_error(400, "全量扫描路径必须是目录")
        if kind == "targeted" and not path:
            return self.__api_error(400, "定向同步必须提供 path")
        if kind == "full_scan":
            worker = lambda task_id: self.scan(scan_path=path or None, mon_path=mon_path,
                                               task_id=task_id, record_task=False)
        else:
            worker = lambda task_id: self.__run_targeted_paths(
                task_id, [{"path": path, "monitor_path": mon_path}]
            )
        result = self.__start_task(kind, {"path": path, "monitor_path": mon_path or ""}, worker)
        if not result.get("accepted"):
            return self.__api_error(409, result.get("message", "已有任务正在运行"),
                                    task_id=result.get("task_id"), current=result.get("task"))
        self._page_task_id = result["task_id"]
        return JSONResponse(status_code=202, content={"task_id": result["task_id"],
                                                       "task": result["task"]})

    def __api_retry_task(self, task_id: str, payload: Optional[dict] = Body(default=None)):
        original = self.__get_task(task_id)
        if not original:
            return self.__api_error(404, f"任务不存在：{task_id}")
        payload = payload or {}
        requested_ids = payload.get("item_ids")
        if requested_ids is not None and not isinstance(requested_ids, list):
            return self.__api_error(400, "item_ids 必须是数组")
        selected = []
        for item in original.get("items") or []:
            if requested_ids is not None and item.get("id") not in requested_ids:
                continue
            if item.get("status") == "failed" and item.get("retryable"):
                selected.append(deepcopy(item))
        if not selected:
            return self.__api_error(400, "没有可重试的失败项")
        source_ids = [item.get("id") for item in selected]

        def worker(retry_id):
            self._task_context.allowed_sources = {
                self.__path_key(item.get("source_file")) for item in selected
                if item.get("source_file")
            }
            for item in selected:
                if self.__task_is_stopped(retry_id):
                    break
                source_file = item.get("source_file")
                monitor_path = item.get("monitor_path") or self.__find_monitor_path(source_file)
                if not monitor_path:
                    result = self.__task_result(source_file, item.get("target_file"), status="failed",
                                                action="retry", stage="mapping",
                                                reason="找不到对应的监控目录", retryable=False)
                    self.__task_discover(retry_id)
                    self.__task_record_result(retry_id, result)
                    continue
                self.__handle_file(source_file, monitor_path,
                                   force=item.get("stage") in {"format", "generate", "copy", "source"},
                                   retry_stage=item.get("stage") if item.get("stage") in {"push", "emby"} else "")

        result = self.__start_task("retry", {"source_task_id": task_id,
                                                  "item_ids": source_ids}, worker)
        if not result.get("accepted"):
            return self.__api_error(409, result.get("message", "已有任务正在运行"),
                                    task_id=result.get("task_id"), current=result.get("task"))
        self._page_task_id = result["task_id"]
        self._task_selected_items.pop(task_id, None)
        return JSONResponse(status_code=202, content={"task_id": result["task_id"],
                                                       "source_task_id": task_id,
                                                       "task": result["task"]})

    def __api_toggle_task_item(self, task_id: str,
                               payload: Optional[dict] = Body(default=None)):
        """Toggle a retryable failure selection used by the native task page."""
        task = self.__get_task(task_id)
        if not task:
            return self.__api_error(404, f"任务不存在：{task_id}")
        payload = payload or {}
        item_id = str(payload.get("item_id") or "").strip()
        if not item_id:
            return self.__api_error(400, "item_id 不能为空")
        item = next((item for item in task.get("items") or []
                     if item.get("id") == item_id), None)
        if not item:
            return self.__api_error(404, f"任务明细不存在：{item_id}")
        if item.get("status") != "failed" or not item.get("retryable"):
            return self.__api_error(400, "只有可重试的失败项可以加入批量重试")
        with self._task_history_lock:
            selected = self._task_selected_items.setdefault(task_id, set())
            if item_id in selected:
                selected.remove(item_id)
                checked = False
            else:
                selected.add(item_id)
                checked = True
            selected_ids = sorted(selected)
        return {"task_id": task_id, "item_id": item_id,
                "selected": checked, "selected_item_ids": selected_ids}

    def __api_get_tasks(self, status: str = None):
        if status and status not in {"running", "success", "partial", "failed", "interrupted"}:
            return self.__api_error(400, "无效的任务状态")
        return self.__api_tasks(status=status)

    def __api_get_task(self, task_id: str, status: str = None, page: int = 1, page_size: int = 50):
        if status and status not in {"success", "skipped", "failed"}:
            return self.__api_error(400, "明细状态只能是 success、skipped 或 failed")
        if not self.__get_task(task_id):
            return self.__api_error(404, f"任务不存在：{task_id}")
        self._page_task_id = task_id
        self._page_filter_status = status or None
        return self.__api_task_detail(task_id, status, page, page_size)

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
        self._task_history_json = os.path.join(self.get_data_path(), "task_history.json")
        self._task_history = []
        self._task_active_id = None
        self._task_stop_event = threading.Event()
        self._task_stop_events = {}
        with self._task_thread_lock:
            if not self._task_thread or not self._task_thread.is_alive():
                self._task_thread = None
                self._task_thread_task_id = None
        self._task_generations = {}
        self._task_history_dirty = 0
        self._task_history_last_saved = 0.0
        self._page_filter_status = None
        self._page_task_id = None
        self._task_selected_items = {}
        self._config_errors = []
        self.mediaserver_helper = MediaServerHelper()
        self.__load_generated_files()
        self.__load_task_history()

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

        # Saving a disabled plugin still reinitializes it. Validate here so the
        # form can show actionable feedback before a task is ever started.
        if not self._enabled and not self._onlyonce:
            self._config_errors = self.__validate_monitor_confs(self._monitor_confs)

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
                    self._config_errors.append(f"目录配置格式错误：{monitor_conf}")
                    continue
                # 检查媒体库目录是不是下载目录的子目录
                try:
                    if (strm_dir and (
                            self.__is_path_within(strm_dir, local_dir)
                            or self.__is_path_within(local_dir, strm_dir))):
                        logger.warning(f"{strm_dir} 与 {local_dir} 存在包含关系，无法监控")
                        self.systemmessage.put(f"{strm_dir} 与 {local_dir} 存在包含关系，无法监控")
                        self._config_errors.append(f"目录配置存在包含关系：{local_dir} 与 {strm_dir}")
                        continue
                except Exception as e:
                    logger.debug(str(e))

                if not format_str or not any(token in format_str for token in ("{local_file}", "{cloud_file}")):
                    logger.error(f"{monitor_conf} 格式化模板缺少 {{local_file}} 或 {{cloud_file}}")
                    self.systemmessage.put(f"{local_dir} 格式化模板无效，缺少文件路径占位符")
                    self._config_errors.append(f"{local_dir} 格式化模板缺少 {{local_file}} 或 {{cloud_file}}")
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

    def scan(self, scan_path: str = None, mon_path: str = None,
             task_id: str = None, record_task: bool = True, channel=None, userid=None):
        """
        全量执行
        """
        if record_task and not task_id:
            scope = {"path": scan_path or "", "monitor_path": mon_path or ""}
            return self.__start_task(
                "full_scan", scope,
                lambda _task_id: self.scan(scan_path=scan_path, mon_path=mon_path,
                                           task_id=_task_id, record_task=False),
                channel=channel, userid=userid,
            )
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
                    if task_id and self.__task_is_stopped(task_id):
                        return self.__get_task(task_id)
                    source_file = os.path.join(root, file)
                    if self.__is_ignored_path(source_file):
                        continue

                    self.__handle_file(event_path=source_file, mon_path=current_mon_path)
        logger.info("全量执行完成")
        return self.__get_task(task_id) if task_id else None

    @eventmanager.register(EventType.PluginAction)
    def strm_one(self, event: Event = None):
        if event:
            event_data = event.event_data
            if not event_data:
                return
            if event_data.get("action") == "CloudStrmHelper":
                self.scan(channel=event_data.get("channel"), userid=event_data.get("user"))
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
            self.scan(scan_path=event_path, mon_path=mon_path, record_task=False)

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

    def __handle_file(self, event_path: str, mon_path: str, force: bool = False,
                      retry_stage: str = "") -> dict:
        task_id = getattr(self._task_context, "task_id", None)
        if task_id and self.__task_is_stopped(task_id):
            result = self.__task_result(event_path, status="skipped", action="stopped",
                                        stage="queue", reason="任务已停止", monitor_path=mon_path)
            self.__task_discover(task_id)
            self.__task_record_result(task_id, result)
            return result
        if task_id and not self.__task_claim_source(task_id, event_path):
            return None
        if task_id:
            self.__task_discover(task_id)
        result = self.__process_file(
            event_path=event_path, mon_path=mon_path, force=force, retry_stage=retry_stage
        )
        if task_id and result:
            self.__task_record_result(task_id, result)
        return result

    def __process_file(self, event_path: str, mon_path: str, force: bool = False,
                       retry_stage: str = "") -> dict:
        """
        同步一个文件
        :param event_path: 事件文件路径
        :param mon_path: 监控目录
        """
        source_path = os.path.normpath(str(event_path))
        processing_key = (mon_path, self.__path_key(source_path))
        with self._state_lock:
            if processing_key in self._processing_paths:
                return self.__task_result(source_path, status="skipped", action="busy",
                                          stage="queue", reason="文件正在处理中",
                                          monitor_path=mon_path)
            self._processing_paths.add(processing_key)
        try:
            source = Path(source_path)
            if not source.is_file():
                return self.__task_result(source_path, status="failed", action="read",
                                          stage="source", reason="源文件不存在或不可读取",
                                          retryable=True, monitor_path=mon_path)
            if self.__is_ignored_path(source_path):
                return self.__task_result(source_path, status="skipped", action="ignore",
                                          stage="filter", reason="文件属于忽略路径",
                                          monitor_path=mon_path)

            cloud_dir = self._cloud_dir_conf.get(mon_path)
            strm_dir = self._strm_dir_conf.get(mon_path)
            format_str = self._format_conf.get(mon_path)
            relative = self.__relative_path(source_path, mon_path)
            if relative is None or not strm_dir:
                logger.warning(f"文件 {source_path} 不在监控目录 {mon_path} 内，跳过")
                return self.__task_result(source_path, status="failed", action="map",
                                          stage="mapping", reason="文件不在有效监控目录内",
                                          retryable=False, monitor_path=mon_path)

            target_file = self.__map_path(source_path, mon_path, strm_dir)
            cloud_file = self.__join_remote_path(cloud_dir, relative)
            suffix = source.suffix.lower()

            if suffix in self._media_exts:
                strm_path = os.path.splitext(target_file)[0] + ".strm"
                if retry_stage in {"push", "emby"}:
                    if retry_stage == "push":
                        push_result = self.__push_strm_file(strm_path, source_path)
                        if not push_result.get("ok"):
                            return self.__task_result(
                                source_path, strm_path, status="failed", action="push",
                                stage="push", reason=push_result.get("reason", "任务推送失败"),
                                retryable=True, monitor_path=mon_path,
                            )
                        return self.__task_result(source_path, strm_path, status="success",
                                                  action="push", stage="push",
                                                  monitor_path=mon_path)
                    refresh_result = self.__refresh_emby_file(strm_path, update_type="Modified")
                    if not refresh_result.get("ok"):
                        return self.__task_result(
                            source_path, strm_path, status="failed", action="refresh",
                            stage="emby", reason=refresh_result.get("reason", "媒体库刷新失败"),
                            retryable=True, monitor_path=mon_path,
                        )
                    return self.__task_result(source_path, strm_path, status="success",
                                              action="refresh", stage="emby",
                                              monitor_path=mon_path)
                strm_content = self.__format_content(
                    format_str=format_str,
                    local_file=source_path,
                    cloud_file=cloud_file,
                    uriencode=self._uriencode,
                )
                if strm_content is None:
                    logger.error(f"{source_path} 未生成 STRM：格式化模板无效")
                    return self.__task_result(
                        source_path, strm_path, status="failed", action="format",
                        stage="format", reason="格式化模板缺少有效占位符",
                        retryable=True, monitor_path=mon_path,
                    )
                strm_existed = Path(strm_path).is_file()
                strm_result = self.__create_strm_file(
                    strm_file=target_file,
                    strm_content=strm_content,
                    source_file=source_path,
                    force=force,
                )

                related_results = []
                for related_file in self.__find_related_files(source):
                    allowed_sources = getattr(self._task_context, "allowed_sources", None)
                    if allowed_sources is not None and self.__path_key(str(related_file)) not in allowed_sources:
                        continue
                    related_target = self.__map_path(str(related_file), mon_path, strm_dir)
                    if related_target:
                        task_id = getattr(self._task_context, "task_id", None)
                        if task_id and not self.__task_claim_source(task_id, str(related_file)):
                            continue
                        if task_id and not self.__task_claim_sidecar(str(related_file)):
                            continue
                        related_result = self.__handle_other_files(
                            event_path=str(related_file), target_file=related_target, force=force
                        )
                        related_results.append(related_result)
                        if task_id:
                            sidecar_task_result = self.__task_result(
                                str(related_file), related_target,
                                status=related_result.get("status", "failed"),
                                action=related_result.get("action", "copy"),
                                stage=related_result.get("stage", "copy"),
                                reason=related_result.get("reason", ""),
                                retryable=bool(related_result.get("retryable")),
                                monitor_path=mon_path,
                            )
                            self.__task_discover(task_id)
                            self.__task_record_result(task_id, sidecar_task_result)

                changed = strm_result.get("status") == "success" or any(
                    item.get("status") == "success" for item in related_results
                )
                if changed and self._refresh_emby and self._mediaservers:
                    update_type = "Modified" if strm_existed else "Created"
                    refresh_result = self.__refresh_emby_file(strm_path, update_type=update_type)
                    if not refresh_result.get("ok"):
                        return self.__task_result(
                            source_path, strm_path, status="failed", action="refresh",
                            stage="emby", reason=refresh_result.get("reason", "媒体库刷新失败"),
                            retryable=True, monitor_path=mon_path,
                        )
                if strm_result.get("status") == "failed":
                    return self.__task_result(
                        source_path, strm_path, status="failed", action=strm_result.get("action", "generate"),
                        stage=strm_result.get("stage", "generate"),
                        reason=strm_result.get("reason", "STRM 文件生成失败"),
                        retryable=bool(strm_result.get("retryable")), monitor_path=mon_path,
                    )
                if strm_result.get("status") == "success" or any(
                    item.get("status") == "success" for item in related_results
                ):
                    action = strm_result.get("action") or "generate"
                    if any(item.get("status") == "success" for item in related_results):
                        action = f"{action},sidecar"
                    return self.__task_result(source_path, strm_path, status="success", action=action,
                                              stage=strm_result.get("stage", "generate"),
                                              monitor_path=mon_path)
                return self.__task_result(
                    source_path, strm_path, status="skipped", action=strm_result.get("action", "skip"),
                    stage=strm_result.get("stage", "generate"),
                    reason=strm_result.get("reason", "目标文件无需更新"), monitor_path=mon_path,
                )
            else:
                if retry_stage == "emby":
                    refresh_result = self.__refresh_emby_file(
                        self.__related_strm_path(target_file), update_type="Modified"
                    )
                    if not refresh_result.get("ok"):
                        return self.__task_result(
                            source_path, target_file, status="failed", action="refresh",
                            stage="emby", reason=refresh_result.get("reason", "媒体库刷新失败"),
                            retryable=True, monitor_path=mon_path,
                        )
                    return self.__task_result(
                        source_path, target_file, status="success", action="refresh",
                        stage="emby", monitor_path=mon_path,
                    )
                copy_result = self.__handle_other_files(event_path=source_path, target_file=target_file,
                                                        force=force)
                if copy_result.get("status") == "success" and self._refresh_emby and self._mediaservers:
                    refresh_result = self.__refresh_emby_file(
                        self.__related_strm_path(target_file), update_type="Modified"
                    )
                    if not refresh_result.get("ok"):
                        return self.__task_result(
                            source_path, target_file, status="failed", action="refresh",
                            stage="emby", reason=refresh_result.get("reason", "媒体库刷新失败"),
                            retryable=True, monitor_path=mon_path,
                        )
                return self.__task_result(
                    source_path, target_file, status=copy_result.get("status", "failed"),
                    action=copy_result.get("action", "copy"),
                    stage=copy_result.get("stage", "copy"),
                    reason=copy_result.get("reason", ""),
                    retryable=bool(copy_result.get("retryable")), monitor_path=mon_path,
                )
        except Exception as e:
            logger.error("目录监控发生错误：%s - %s" % (str(e), traceback.format_exc()))
            return self.__task_result(
                source_path, status="failed", action="process", stage="process",
                reason=str(e), retryable=True, monitor_path=mon_path,
            )
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

    def __handle_other_files(self, event_path: str, target_file: str, force: bool = False) -> dict:
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
        if not should_copy:
            return {"status": "skipped", "action": "disabled", "stage": "copy",
                    "reason": "未启用该文件类型的复制"}
        if not source.is_file():
            return {"status": "failed", "action": "copy", "stage": "source",
                    "reason": "旁车文件不存在", "retryable": True}
        try:
            target = Path(target_file)
            if self.__path_key(str(source)) == self.__path_key(str(target)):
                return {"status": "skipped", "action": "same_path", "stage": "copy",
                        "reason": "源文件与目标文件相同"}
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file() and not force:
                source_stat = source.stat()
                target_stat = target.stat()
                if (source_stat.st_size == target_stat.st_size
                        and source_stat.st_mtime_ns == target_stat.st_mtime_ns):
                    return {"status": "skipped", "action": "unchanged", "stage": "copy",
                            "reason": "目标文件内容未变化"}
            temp_file = target.with_name(f".{target.name}.tmp")
            with lock:
                shutil.copy2(str(source), str(temp_file))
                os.replace(str(temp_file), str(target))
            self.__mark_generated_file(str(target))
            logger.info(f"复制旁车文件 {source} 到 {target}")
            return {"status": "success", "action": "copy", "stage": "copy"}
        except Exception as err:
            logger.error(f"复制旁车文件失败 {source} -> {target_file}：{err}")
            return {"status": "failed", "action": "copy", "stage": "copy",
                    "reason": str(err), "retryable": True}

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
        if not any(token in format_str for token in ("{local_file}", "{cloud_file}")):
            return None
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

    def __push_strm_file(self, strm_file: str, source_file: str = None) -> dict:
        if not self._url:
            return {"ok": True}
        try:
            content = Path(strm_file).read_text(encoding="utf-8")
            response = RequestUtils(content_type="application/json").post(
                url=self._url, json={"path": content, "type": "add"}
            )
            if response is None:
                return {"ok": False, "reason": "任务推送未收到响应"}
            if getattr(response, "status_code", 0) not in range(200, 300):
                return {"ok": False, "reason": f"任务推送返回 HTTP {response.status_code}"}
            return {"ok": True}
        except Exception as err:
            logger.warning(f"STRM 任务推送失败 {strm_file}：{err}")
            return {"ok": False, "reason": str(err)}

    def __create_strm_file(self, strm_file: str, strm_content: str, source_file: str = None,
                           force: bool = False) -> dict:

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
            if Path(strm_file).exists() and not (self._cover or force):
                logger.info(f"目标文件 {strm_file} 已存在")
                return {"status": "skipped", "action": "exists", "stage": "generate",
                        "reason": "目标文件已存在且未开启覆盖"}
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
                push_result = self.__push_strm_file(strm_file, source_file)
                if not push_result.get("ok"):
                    return {"status": "failed", "action": "push", "stage": "push",
                            "reason": push_result.get("reason", "任务推送失败"),
                            "retryable": True}

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

            return {"status": "success", "action": "overwrite" if force else "generate",
                    "stage": "generate"}
        except Exception as e:
            logger.error(f"创建strm文件失败 {strm_file} -> {str(e)}")
            return {"status": "failed", "action": "generate", "stage": "generate",
                    "reason": str(e), "retryable": True}
        return {"status": "failed", "action": "generate", "stage": "generate",
                "reason": "STRM 文件生成失败", "retryable": True}

    def __refresh_emby_file(self, strm_file: str, update_type: str = "Created"):
        """
        通知emby刷新文件
        """
        try:
            emby_servers = self.mediaserver_helper.get_services(
                name_filters=self._mediaservers, type_filter="emby"
            )
            if not emby_servers:
                logger.error("未配置Emby媒体服务器")
                return {"ok": False, "reason": "未配置可用的 Emby 媒体服务器"}

            mapped_file = self.__get_path(paths=self._emby_paths, file_path=strm_file)
            failures = []
            for emby_name, emby_server in emby_servers.items():
                try:
                    res = emby_server.instance.post_data(
                        url=f'[HOST]emby/Library/Media/Updated?api_key=[APIKEY]&reqformat=json',
                        data=json.dumps({
                            "Updates": [{"Path": mapped_file, "UpdateType": update_type}]
                        }),
                        headers={"Content-Type": "application/json"}
                    )
                    if res and res.status_code in [200, 204]:
                        logger.info(f"媒体服务器 {emby_name} 已刷新 {mapped_file}")
                    else:
                        status_code = res.status_code if res else "无响应"
                        failures.append(f"{emby_name}: HTTP {status_code}")
                        logger.error(f"通知媒体服务器 {emby_name} 刷新文件 {mapped_file} 失败，错误码：{status_code}")
                except Exception as err:
                    failures.append(f"{emby_name}: {err}")
                    logger.error(f"通知媒体服务器 {emby_name} 刷新新增文件失败：{err}")
            return {"ok": not failures,
                    "reason": "；".join(failures) if failures else ""}
        except Exception as err:
            logger.error(f"获取 Emby 服务或刷新文件失败：{err}")
            return {"ok": False, "reason": str(err)}

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

    def __iter_task_files(self, path: str):
        source = Path(path)
        if source.is_file():
            yield str(source)
            return
        if not source.is_dir():
            return
        for root, dirs, files in os.walk(str(source)):
            dirs[:] = [directory for directory in dirs
                       if directory.lower() not in self._ignored_dir_names
                       and not directory.startswith(".")]
            for file_name in files:
                file_path = os.path.join(root, file_name)
                if not self.__is_ignored_path(file_path):
                    yield file_path

    def __run_targeted_paths(self, task_id: str, targets: list):
        for target in targets:
            if self.__task_is_stopped(task_id):
                return
            path = target.get("path")
            mon_path = target.get("monitor_path")
            limit = target.get("limit")
            if limit is not None and Path(path).is_dir():
                sub_paths = [Path(path) / item for item in os.listdir(path)
                             if (Path(path) / item).is_dir()]
                sub_paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
                paths = []
                for sub_path in sub_paths[:int(limit)]:
                    paths.extend(self.__iter_task_files(str(sub_path)))
            else:
                paths = self.__iter_task_files(path)
            for source_file in paths:
                if self.__task_is_stopped(task_id):
                    return
                self.__handle_file(event_path=source_file, mon_path=mon_path)

    def __resolve_command_targets(self, args: str) -> Tuple[list, str]:
        args = str(args or "").strip()
        if not args:
            return [], "缺少同步路径或分类参数"

        direct_path = Path(args)
        direct_mon = self.__find_monitor_path(args)
        if direct_mon and direct_path.exists():
            return [{"path": str(direct_path), "monitor_path": direct_mon}], ""

        args_arr = args.split(maxsplit=1)
        category = args_arr[0] if len(args_arr) == 2 else None
        remainder = args_arr[1] if len(args_arr) == 2 else args
        limit = int(remainder) if category and remainder.isdigit() else None
        if category and Path(category).is_dir() and limit is not None:
            mon_path = self.__find_monitor_path(category)
            if not mon_path:
                return [], f"未找到 {category} 对应的监控目录"
            return [{"path": category, "monitor_path": mon_path, "limit": limit}], ""

        targets = []
        for mon_path, mon_category in self._category_conf.items():
            if not mon_category:
                continue
            if category and str(category) in str(mon_category):
                parent_path = os.path.join(mon_path, category)
                if limit is not None:
                    if Path(parent_path).is_dir():
                        targets.append({"path": parent_path, "monitor_path": mon_path,
                                        "limit": limit})
                else:
                    requested = os.path.join(parent_path, remainder)
                    related_paths = self.__find_related_paths(requested)
                    targets.extend({"path": path, "monitor_path": mon_path}
                                    for path in related_paths)
            elif not category and str(args) in str(mon_category):
                parent_path = os.path.join(mon_path, args)
                if Path(parent_path).exists():
                    targets.append({"path": parent_path, "monitor_path": mon_path})

        if targets:
            return targets, ""
        return [], f"未检索到 {args}，请检查输入是否正确"

    @eventmanager.register(EventType.PluginAction)
    def remote_sync_one(self, event: Event = None):
        if not event:
            return
        event_data = event.event_data or {}
        if event_data.get("action") != "strm_one":
            return
        args = event_data.get("arg_str")
        targets, error = self.__resolve_command_targets(args)
        if error:
            logger.error(error)
            if event_data.get("user"):
                self.post_message(channel=event_data.get("channel"), title=error,
                                  userid=event_data.get("user"))
            return
        result = self.__start_task(
            "targeted", {"path": args or "", "targets": targets},
            lambda task_id: self.__run_targeted_paths(task_id, targets),
            channel=event_data.get("channel"), userid=event_data.get("user"),
        )
        if not result.get("accepted") and event_data.get("user"):
            self.post_message(channel=event_data.get("channel"),
                              title=f"已有任务正在运行：{result.get('task_id')}",
                              userid=event_data.get("user"))

    @staticmethod
    def __find_related_paths(base_path):
        related_paths = []
        base_dir = os.path.dirname(base_path)
        base_name = os.path.basename(base_path)

        try:
            entries = os.listdir(base_dir)
        except OSError:
            return related_paths
        for entry in entries:
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
        return [
            {
                "path": "/tasks",
                "endpoint": self.__api_get_tasks,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "读取 CloudStrm 任务列表",
            },
            {
                "path": "/tasks/{task_id}",
                "endpoint": self.__api_get_task,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "读取 CloudStrm 任务详情",
            },
            {
                "path": "/tasks",
                "endpoint": self.__api_start_task,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "启动 CloudStrm 扫描任务",
            },
            {
                "path": "/tasks/{task_id}/retry",
                "endpoint": self.__api_retry_task,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "重试 CloudStrm 失败项",
            },
            {
                "path": "/tasks/{task_id}/selection",
                "endpoint": self.__api_toggle_task_item,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "选择 CloudStrm 失败项",
            },
        ]

    def __legacy_get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """保留旧版表单结构，便于回滚时参考；实际配置入口见下方 get_form。"""
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

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """按工作流组织配置，字段名和数据格式保持与旧版兼容。"""
        def switch(model, label, color=None):
            props = {"model": model, "label": label}
            if color:
                props["color"] = color
            return {"component": "VSwitch", "props": props}

        def field(component, model, label, **props):
            values = {"model": model, "label": label}
            values.update(props)
            return {"component": component, "props": values}

        def col(content, md=12):
            return {"component": "VCol", "props": {"cols": 12, "md": md},
                    "content": content if isinstance(content, list) else [content]}

        def row(*columns):
            return {"component": "VRow", "content": list(columns)}

        def panel(title, content):
            return {"component": "VExpansionPanel", "content": [
                {"component": "VExpansionPanelTitle", "text": title},
                {"component": "VExpansionPanelText", "content": content},
            ]}

        emby_configs = self.mediaserver_helper.get_configs() if self.mediaserver_helper else {}
        emby_items = [
            {"title": config.name, "value": config.name}
            for config in emby_configs.values() if getattr(config, "type", "") == "emby"
        ]
        template_warning = {
            "component": "VAlert",
            "props": {
                "type": "warning", "variant": "tonal",
                "text": "目录模板必须包含 {local_file} 或 {cloud_file}；保存后会立即校验并在这里显示错误。",
            },
        }
        config_error_alert = {
            "component": "VAlert",
            "props": {
                "type": "error", "variant": "tonal",
                "text": "；".join(self._config_errors),
            },
        }
        config_help = {
            "component": "VAlert",
            "props": {
                "type": "info", "variant": "tonal",
                "text": "目录配置使用 # 分隔四段：监控目录#STRM目录#云盘目录#模板。模板必须包含 {local_file} 或 {cloud_file}。",
            },
        }
        directory_content = [config_help, template_warning]
        if self._config_errors:
            directory_content.append(config_error_alert)
        directory_content.extend([
            row(col(field("VTextarea", "monitor_confs", "目录配置", rows=5,
                         placeholder="/mnt/media#/mnt/library#/cloud/media#https://host/{cloud_file}"), 12)),
            row(col(field("VTextarea", "emby_path", "媒体库路径映射", rows=2,
                         placeholder="本地路径=>Emby路径，多组用英文逗号分隔"), 6),
                col(field("VTextarea", "path_replacements", "STRM 路径替换规则", rows=3,
                         placeholder="源路径=>目标路径，每行一条；兼容旧版冒号格式"), 6)),
        ])
        form = [{
            "component": "VForm",
            "content": [{
                "component": "VExpansionPanels",
                "props": {"variant": "accordion", "multiple": True},
                "content": [
                    panel("基础设置", [
                        row(col(switch("enabled", "启用插件"), 3),
                            col(switch("monitor", "实时监控"), 3),
                            col(switch("notify", "任务与入库通知"), 3),
                            col(switch("onlyonce", "保存后立即执行一次"), 3)),
                        row(col(field("VTextField", "interval", "入库通知延迟（秒）",
                                     type="number", min=1, placeholder="10"), 4)),
                    ]),
                    panel("文件处理", [
                        row(col(switch("cover", "覆盖已存在文件"), 3),
                            col(switch("copy_files", "复制旁车文件"), 3),
                            col(switch("copy_subtitles", "复制字幕文件"), 3),
                            col(switch("sync_delete", "同步删除生成文件"), 3)),
                    ]),
                    panel("目录映射", [
                        *directory_content,
                    ]),
                    panel("媒体格式", [
                        row(col(field("VTextarea", "rmt_mediaext", "视频格式", rows=2,
                                     placeholder=self._default_rmt_mediaext), 6),
                            col(field("VTextarea", "other_mediaext", "非媒体格式", rows=2,
                                     placeholder=self._default_other_mediaext), 6)),
                    ]),
                    panel("媒体库与高级设置", [
                        row(col({"component": "VSelect", "props": {
                            "multiple": True, "chips": True, "clearable": True,
                            "model": "mediaservers", "label": "Emby 媒体服务器", "items": emby_items,
                        }}, 6),
                            col(switch("refresh_emby", "生成后刷新 Emby"), 6)),
                        row(col(switch("uriencode", "云盘路径 URL 编码"), 4),
                            col(field("VTextField", "url", "任务推送 URL",
                                      placeholder="POST JSON：path、type=add"), 8)),
                    ]),
                ],
            }],
        }]
        model = {
            "enabled": False, "notify": False, "monitor": False, "cover": False,
            "onlyonce": False, "copy_files": False, "uriencode": False,
            "copy_subtitles": False, "sync_delete": False, "refresh_emby": False,
            "mediaservers": [], "monitor_confs": "", "emby_path": "",
            "interval": 10, "url": "",
            "other_mediaext": self._default_other_mediaext,
            "rmt_mediaext": self._default_rmt_mediaext, "path_replacements": "",
        }
        return form, model

    def get_page(self) -> List[dict]:
        data = self.__api_tasks()
        current = data.get("current") or {}
        current_stats = current.get("stats") or {}
        summaries = data.get("tasks") or []
        retry_relations = {}
        for related_task in summaries:
            related_scope = related_task.get("scope") or {}
            source_task_id = related_scope.get("source_task_id")
            if related_task.get("kind") == "retry" and source_task_id:
                retry_relations.setdefault(source_task_id, []).append(related_task.get("id"))
        status_names = {
            "running": "运行中", "success": "成功", "partial": "部分成功",
            "failed": "失败", "interrupted": "已中断",
        }
        kind_names = {"full_scan": "全量扫描", "targeted": "定向同步", "retry": "失败重试"}

        def chip(text, color="default"):
            return {"component": "VChip", "props": {"size": "small", "color": color,
                                                       "variant": "tonal"}, "text": text}

        task_rows = []
        for task in summaries:
            stats = task.get("stats") or {}
            task_rows.append({
                "id": task.get("id"),
                "时间": task.get("finished_at") or task.get("created_at"),
                "类型": kind_names.get(task.get("kind"), task.get("kind")),
                "状态": status_names.get(task.get("status"), task.get("status")),
                "成功": stats.get("success", 0),
                "跳过": stats.get("skipped", 0),
                "失败": stats.get("failed", 0),
                "耗时": f"{task.get('duration_seconds', 0) or 0:.1f}s",
                "关联重试": ", ".join(retry_relations.get(task.get("id"), [])),
            })

        task_headers = [
            {"title": "时间", "key": "时间"},
            {"title": "类型", "key": "类型"},
            {"title": "状态", "key": "状态"},
            {"title": "成功", "key": "成功"},
            {"title": "跳过", "key": "跳过"},
            {"title": "失败", "key": "失败"},
            {"title": "耗时", "key": "耗时"},
            {"title": "关联重试", "key": "关联重试"},
        ]
        task_detail_views = []
        for task in summaries:
            task_id_value = task.get("id")
            if not task_id_value:
                continue
            task_stats = task.get("stats") or {}
            task_detail_views.append({
                "component": "VListItem",
                "props": {
                    "title": f"{kind_names.get(task.get('kind'), task.get('kind'))} · "
                             f"{status_names.get(task.get('status'), task.get('status'))}",
                    "subtitle": (
                        f"时间：{task.get('finished_at') or task.get('created_at') or '-'}；"
                        f"成功 {task_stats.get('success', 0)}，跳过 {task_stats.get('skipped', 0)}，"
                        f"失败 {task_stats.get('failed', 0)}；ID：{task_id_value}"
                    ),
                    "lines": "three",
                },
                "content": [{
                    "component": "VBtn",
                    "props": {"prependIcon": "mdi-file-document-outline", "size": "small",
                               "variant": "tonal"},
                    "text": "查看详情",
                    "events": {"click": {"api": f"plugin/{self.__class__.__name__}/tasks/{task_id_value}",
                                                 "method": "GET", "params": {}}},
                }],
            })
        current_label = status_names.get(current.get("status"), "空闲") if current else "空闲"
        current_total = max(1, current_stats.get("discovered", 0))
        current_progress = min(100, round(current_stats.get("processed", 0) * 100 / current_total)) if current else 0
        latest_id = self._page_task_id or (current.get("id") if current else (summaries[0].get("id") if summaries else ""))
        latest_task = self.__get_task(latest_id) if latest_id else None
        latest_items = (latest_task or {}).get("items") or []
        if self._page_filter_status:
            latest_items = [item for item in latest_items
                            if item.get("status") == self._page_filter_status]
        latest_items = latest_items[:100]
        item_rows = []
        retryable_failed_ids = []
        for item in latest_items:
            item_status = item.get("status") or ""
            if item_status == "failed" and item.get("retryable"):
                retryable_failed_ids.append(item.get("id"))
            item_rows.append({
                "来源": item.get("source_file") or "",
                "目标": item.get("target_file") or "",
                "动作": item.get("action") or "",
                "状态": status_names.get(item_status, item_status),
                "阶段": item.get("stage") or "",
                "原因": item.get("reason") or "",
            })
        item_headers = [
            {"title": "来源", "key": "来源"},
            {"title": "目标", "key": "目标"},
            {"title": "动作", "key": "动作"},
            {"title": "状态", "key": "状态"},
            {"title": "阶段", "key": "阶段"},
            {"title": "原因", "key": "原因"},
        ]
        task_id = latest_id
        detail_url = f"plugin/{self.__class__.__name__}/tasks/{task_id}" if task_id else ""
        retry_url = f"plugin/{self.__class__.__name__}/tasks/{task_id}/retry" if task_id else ""
        selection_url = f"plugin/{self.__class__.__name__}/tasks/{task_id}/selection" if task_id else ""
        with self._task_history_lock:
            selected_retryable_ids = set(self._task_selected_items.get(task_id, set())) if task_id else set()
        selected_retryable_ids = [item_id for item_id in retryable_failed_ids
                                  if item_id in selected_retryable_ids]
        latest_scope = (latest_task or {}).get("scope") or {}
        relation_text = ""
        if latest_task and latest_task.get("kind") == "retry":
            relation_text = f"来源任务：{latest_scope.get('source_task_id') or '未知'}"
        elif latest_task and retry_relations.get(latest_task.get("id")):
            relation_text = f"关联重试任务：{', '.join(retry_relations[latest_task.get('id')])}"
        detail_actions = []
        if retry_url and retryable_failed_ids:
            detail_actions.append({
                "component": "VBtn",
                "props": {"prependIcon": "mdi-replay", "color": "error", "variant": "tonal"},
                "text": f"批量重试全部失败项（{len(retryable_failed_ids)}）",
                "events": {"click": {"api": retry_url, "method": "POST",
                                             "params": {"item_ids": retryable_failed_ids}}},
            })
        if retry_url and selected_retryable_ids:
            detail_actions.append({
                "component": "VBtn",
                "props": {"prependIcon": "mdi-checkbox-marked-outline",
                           "color": "primary", "variant": "flat"},
                "text": f"重试已选失败项（{len(selected_retryable_ids)}）",
                "events": {"click": {"api": retry_url, "method": "POST",
                                             "params": {"item_ids": selected_retryable_ids}}},
            })
        if relation_text:
            detail_actions.append({"component": "VChip", "props": {"size": "small", "variant": "tonal"},
                                   "text": relation_text})
        failed_item_views = []
        for item in latest_items:
            if item.get("status") != "failed" or not item.get("retryable") or not retry_url:
                continue
            failed_item_views.append({
                "component": "VListItem",
                "props": {
                    "title": item.get("source_file") or "未知源文件",
                    "subtitle": f"阶段：{item.get('stage') or '未知'}；原因：{item.get('reason') or '未提供'}",
                    "lines": "three",
                },
                "content": [
                    {
                        "component": "VCheckbox",
                        "props": {"modelValue": item.get("id") in selected_retryable_ids,
                                   "label": "选择", "density": "compact",
                                   "hideDetails": True, "color": "primary"},
                        "events": {"click": {"api": selection_url, "method": "POST",
                                                     "params": {"item_id": item.get("id")}}},
                    },
                    {
                        "component": "VBtn",
                        "props": {"prependIcon": "mdi-replay", "size": "small",
                                   "color": "error", "variant": "tonal"},
                        "text": "重试此项",
                        "events": {"click": {"api": retry_url, "method": "POST",
                                                     "params": {"item_ids": [item.get("id")]}}},
                    },
                ],
            })
        failed_item_list = {
            "component": "VList", "props": {"density": "compact", "lines": "three"},
            "content": failed_item_views or [{"component": "VListItem", "props": {"title": "没有可重试的失败项"}}],
        }
        detail_filters = []
        for filter_status, filter_label in (("", "全部"), ("success", "成功"),
                                             ("skipped", "跳过"), ("failed", "失败")):
            detail_filters.append({
                "component": "VBtn",
                "props": {"size": "small", "variant": "text",
                           "prependIcon": "mdi-filter-variant" if filter_status else "mdi-filter-off-outline"},
                "text": filter_label,
                "events": {"click": {"api": detail_url, "method": "GET",
                                             "params": ({"status": filter_status} if filter_status else {})}},
            })
        page = [
            {
                "component": "VCard",
                "props": {"variant": "tonal", "class": "mb-4"},
                "content": [
                    {"component": "VCardTitle", "text": "任务中心"},
                    {"component": "VCardText", "content": [
                        {"component": "VRow", "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 3},
                             "content": [{"component": "VChip", "props": {"color": "info", "variant": "tonal"},
                                              "text": f"当前任务：{current_label}"}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 9},
                             "content": [{"component": "VProgressLinear", "props": {"modelValue": current_progress,
                                                                                         "height": 8, "rounded": True,
                                                                                         "color": "primary",
                                                                                         "indeterminate": bool(current and not current_stats.get("discovered"))}}]},
                        ]},
                        {"component": "VRow", "content": [
                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [chip(f"总数 {current_stats.get('discovered', 0)}")]},
                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [chip(f"已处理 {current_stats.get('processed', 0)}")]},
                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [chip(f"成功 {current_stats.get('success', 0)}", "success")]},
                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [chip(f"跳过 {current_stats.get('skipped', 0)}", "warning")]},
                            {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [chip(f"失败 {current_stats.get('failed', 0)}", "error")]},
                        ]},
                    ]},
                    {"component": "VCardActions", "content": [
                        {"component": "VBtn", "props": {"prependIcon": "mdi-play", "color": "primary", "variant": "flat"},
                         "text": "立即全量扫描", "events": {"click": {"api": f"plugin/{self.__class__.__name__}/tasks", "method": "POST", "params": {"kind": "full_scan"}}}},
                        {"component": "VBtn", "props": {"prependIcon": "mdi-refresh", "variant": "text"},
                         "text": "刷新任务状态", "events": {"click": {"api": f"plugin/{self.__class__.__name__}/tasks", "method": "GET", "params": {}}}},
                    ]},
                ],
            },
            {"component": "VCard", "props": {"class": "mb-4"}, "content": [
                {"component": "VCardTitle", "text": "最近任务"},
                {"component": "VDataTable", "props": {"headers": task_headers, "items": task_rows,
                                                                         "itemsPerPage": 10, "density": "compact",
                                                                         "hover": True, "hideDefaultFooter": False}},
                {"component": "VListSubheader", "text": "打开任务详情"},
                {"component": "VList", "props": {"density": "compact", "lines": "three"},
                 "content": task_detail_views or [{"component": "VListItem", "props": {"title": "暂无历史任务"}}]},
            ]},
            {"component": "VExpansionPanels", "props": {"variant": "accordion"}, "content": [
                {"component": "VExpansionPanel", "content": [
                    {"component": "VExpansionPanelTitle", "text": "最近任务详情"},
                    {"component": "VExpansionPanelText", "content": [
                        {"component": "VAlert", "props": {"type": "info", "variant": "tonal",
                                                                          "text": f"当前查看任务 ID：{task_id or '无'}"}},
                        {"component": "VCardActions", "content": detail_actions},
                        {"component": "VCardActions", "content": detail_filters},
                        {"component": "VDataTable", "props": {"headers": item_headers, "items": item_rows,
                                                                         "itemsPerPage": 10, "density": "compact",
                                                                         "hover": True}},
                        {"component": "VListSubheader", "text": "可重试失败项（支持全部重试或逐项重试）"},
                        failed_item_list,
                        {"component": "VBtn", "props": {"prependIcon": "mdi-open-in-new", "variant": "text",
                                                                       "disabled": not bool(detail_url)},
                         "text": "刷新任务详情", "events": {"click": {"api": detail_url, "method": "GET", "params": {}}}},
                    ]},
                ]},
            ]},
        ]
        return page

    def get_dashboard(self, key: str, **kwargs):
        """Expose a read-only task summary that the dashboard can refresh safely."""
        if key not in {"", "tasks", "task_center"}:
            return None
        refresh = 3 if self.__current_task() else 0
        current = self.__current_task() or {}
        stats = current.get("stats") or {}
        status_names = {
            "running": "运行中", "success": "成功", "partial": "部分成功",
            "failed": "失败", "interrupted": "已中断",
        }
        summary = self.__api_tasks().get("tasks") or []
        rows = []
        for task in summary[:5]:
            task_stats = task.get("stats") or {}
            rows.append({
                "时间": task.get("finished_at") or task.get("created_at"),
                "状态": status_names.get(task.get("status"), task.get("status")),
                "成功": task_stats.get("success", 0),
                "跳过": task_stats.get("skipped", 0),
                "失败": task_stats.get("failed", 0),
            })
        page = [{
            "component": "VRow",
            "content": [
                {"component": "VCol", "props": {"cols": 6, "md": 2},
                 "content": [{"component": "VChip", "props": {"color": "info", "variant": "tonal"},
                              "text": f"状态：{status_names.get(current.get('status'), '空闲')}"}]},
                {"component": "VCol", "props": {"cols": 6, "md": 2},
                 "content": [{"component": "VChip", "props": {"variant": "tonal"},
                              "text": f"已处理 {stats.get('processed', 0)}"}]},
                {"component": "VCol", "props": {"cols": 6, "md": 2},
                 "content": [{"component": "VChip", "props": {"color": "success", "variant": "tonal"},
                              "text": f"成功 {stats.get('success', 0)}"}]},
                {"component": "VCol", "props": {"cols": 6, "md": 2},
                 "content": [{"component": "VChip", "props": {"color": "warning", "variant": "tonal"},
                              "text": f"跳过 {stats.get('skipped', 0)}"}]},
                {"component": "VCol", "props": {"cols": 6, "md": 2},
                 "content": [{"component": "VChip", "props": {"color": "error", "variant": "tonal"},
                              "text": f"失败 {stats.get('failed', 0)}"}]},
            ],
        }, {
            "component": "VDataTable",
            "props": {
                "headers": [
                    {"title": "时间", "key": "时间"}, {"title": "状态", "key": "状态"},
                    {"title": "成功", "key": "成功"}, {"title": "跳过", "key": "跳过"},
                    {"title": "失败", "key": "失败"},
                ],
                "items": rows, "itemsPerPage": 5, "density": "compact",
                "hideDefaultFooter": True,
            },
        }]
        return ({"cols": 12, "md": 12},
                {"refresh": refresh, "border": False, "title": "CloudStrm 任务中心"},
                page)

    def get_dashboard_meta(self):
        return [{"key": "task_center", "name": "任务中心"}]

    def stop_service(self):
        """
        退出插件
        """
        self._task_generation += 1
        active_id = self._task_active_id or self._task_thread_task_id
        active_thread = self._task_thread
        if active_id:
            self._task_stop_event.set()
            stop_event = self._task_stop_events.get(active_id)
            if stop_event:
                stop_event.set()
            with self._task_history_lock:
                active = next((task for task in self._task_history
                               if task.get("id") == active_id and task.get("status") == "running"), None)
                if active:
                    now = self.__task_now()
                    active["status"] = "interrupted"
                    active["finished_at"] = now
                    active["updated_at"] = now
                    active["error"] = "插件重启时任务未完成"
                    active["duration_seconds"] = self.__task_duration(active)
                    self._task_history_dirty += 1
            try:
                self.__save_task_history(force=True)
            except OSError as err:
                logger.warning(f"保存中断任务历史失败：{err}")
            self._task_active_id = None
            if active_thread and active_thread is not threading.current_thread():
                active_thread.join(timeout=2)
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
