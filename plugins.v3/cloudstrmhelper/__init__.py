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
from collections import deque
from datetime import datetime, timedelta
from html import escape as html_escape
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
    plugin_desc = "OpenList + CD2 实时监控，定时全量增量生成 STRM 文件。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/luyang1104/MoviePilot-Plugins/main/icons/cloudstrm.png"
    # 插件版本
    plugin_version = "V1.4.2"
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
    # V1.4.0：定时增量扫描（对应设计稿「定时增量扫描」开关）
    _cron_enabled = True
    _scan_interval = 30
    # V1.4.0：实时事件环形缓冲，供页面 Live Log Feed 使用
    _live_events = deque(maxlen=150)
    _live_events_lock = threading.Lock()
    # V1.4.0：孤儿清理（死链）累计统计，持久化到 stats.json
    _pruned_total = 0
    _stats_json = "stats.json"
    _stats_lock = threading.Lock()
    # V1.4.0：页面暂存配置（开关/映射删除/扩展名移除），保存后生效
    _staged_config = None
    _staged_lock = threading.Lock()
    _page_editing_rule = None

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
    def __shorten_path(path: str, keep: int = 2) -> str:
        """长路径尾部截断：保留最后 keep 段，显示为 …/父目录/文件名。"""
        if not path:
            return ""
        parts = [seg for seg in re.split(r"[\\/]+", str(path)) if seg]
        if len(parts) <= keep:
            return path
        return "…/" + "/".join(parts[-keep:])

    @staticmethod
    def __render_table_html(headers: List[Dict[str, str]], rows: List[Dict[str, Any]],
                            empty_text: str = "暂无数据") -> str:
        """把表头/行数据渲染成轻量 HTML 表格。

        MoviePilot 的 PageRender/DashboardRender 会给每个组件注入默认插槽内容，
        VDataTable 一旦拿到默认插槽就会跳过内置的表头与表体渲染（页面只剩分页条），
        因此表格统一改用 html 字段输出原生 <table>，样式复用 Vuetify 的 v-table 类。
        """
        def cell(value: Any) -> str:
            return html_escape("" if value is None else str(value))

        head_cells = "".join(f"<th class=\"text-left\">{cell(col.get('title'))}</th>"
                             for col in headers)
        if rows:
            body_rows = "".join(
                "<tr>" + "".join(f"<td>{cell(row.get(col.get('key')))}</td>"
                                 for col in headers) + "</tr>"
                for row in rows)
        else:
            body_rows = (f"<tr><td colspan=\"{max(1, len(headers))}\" "
                         f"class=\"text-medium-emphasis\">{cell(empty_text)}</td></tr>")
        return ("<div class=\"v-table v-table--density-compact v-table--hover rounded\">"
                "<div class=\"v-table__wrapper\"><table>"
                f"<thead><tr>{head_cells}</tr></thead><tbody>{body_rows}</tbody>"
                "</table></div></div>")

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

    @staticmethod
    def __count_rule_slots(config: dict) -> int:
        """统计配置中结构化映射规则 rule_i_* 占用的槽位数。"""
        slots = 0
        for key in (config or {}).keys():
            match = re.match(r"^rule_(\d+)_(local|strm)$", str(key))
            if match:
                slots = max(slots, int(match.group(1)) + 1)
        return slots

    @staticmethod
    def __rules_from_monitor_confs(monitor_confs: str) -> List[dict]:
        """把旧版 # 分隔文本解析为结构化映射规则列表。"""
        rules = []
        for raw_line in str(monitor_confs or "").splitlines():
            line = str(raw_line).strip()
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
            local_dir, strm_dir, cloud_dir, format_str = [part.strip() for part in line.split("#", 3)]
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
    def __category_list(value: Any) -> List[str]:
        """split category into tags"""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raw = str(value).strip()
        if not raw:
            return []
        parts = re.split(r"[,，、]+", raw)
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def __category_string(value: Any) -> str:
        """join tags as comma string"""
        return ",".join(CloudStrmHelper.__category_list(value))

    def __rules_from_config(self, config: dict) -> List[dict]:
        """优先读取结构化 rule_i_* 键，缺失时回退解析旧版 monitor_confs 文本。"""
        config = config or {}
        rules = []
        for index in range(self.__count_rule_slots(config)):
            local = str(config.get(f"rule_{index}_local") or "").strip()
            strm = str(config.get(f"rule_{index}_strm") or "").strip()
            if not local and not strm:
                continue
            monitor_value = config.get(f"rule_{index}_monitor")
            rules.append({
                "category": CloudStrmHelper.__category_string(
                    config.get(f"rule_{index}_category") or ""),
                "local": local,
                "strm": strm,
                "cloud": str(config.get(f"rule_{index}_cloud") or "").strip(),
                "format": str(config.get(f"rule_{index}_format") or "").strip(),
                "monitor": bool(monitor_value) if monitor_value is not None else True,
            })
        if rules:
            return rules
        return self.__rules_from_monitor_confs(config.get("monitor_confs") or "")

    @staticmethod
    def __rules_to_monitor_confs(rules: List[dict]) -> str:
        """把结构化规则序列化回旧版文本格式，作为可移植镜像。"""
        lines = []
        for rule in rules or []:
            local = str(rule.get("local") or "").strip()
            strm = str(rule.get("strm") or "").strip()
            if not local and not strm:
                continue
            line = f"{local}#{strm}#{str(rule.get('cloud') or '').strip()}#{str(rule.get('format') or '').strip()}"
            category = CloudStrmHelper.__category_string(rule.get("category"))
            if category:
                line += f"@{category}"
            if not rule.get("monitor", True):
                line += "$0"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def __rules_to_config_keys(rules: List[dict], slots: int) -> Dict[str, Any]:
        """把规则列表展开为 rule_i_* 配置键，空槽位写空串保证旧键被清除。"""
        keys = {}
        for index in range(max(slots, len(rules or []))):
            rule = rules[index] if rules and index < len(rules) else {}
            keys[f"rule_{index}_category"] = CloudStrmHelper.__category_string(
                rule.get("category"))
            keys[f"rule_{index}_local"] = str(rule.get("local") or "")
            keys[f"rule_{index}_strm"] = str(rule.get("strm") or "")
            keys[f"rule_{index}_cloud"] = str(rule.get("cloud") or "")
            keys[f"rule_{index}_format"] = str(rule.get("format") or "")
            keys[f"rule_{index}_monitor"] = bool(rule.get("monitor", True)) if rule else True
        return keys

    def __log_event(self, tag: str, message: str):
        """追加一条实时事件，供页面 Live Log Feed 展示；任何异常都不影响主流程。"""
        try:
            with self._live_events_lock:
                self._live_events.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "tag": str(tag or "EVENT"),
                    "message": str(message or ""),
                })
        except Exception:
            pass

    def __live_event_snapshot(self, limit: int = 40) -> List[dict]:
        with self._live_events_lock:
            events = list(self._live_events)
        return events[-limit:]

    def __load_stats(self):
        try:
            if Path(self._stats_json).is_file():
                with open(self._stats_json, "r", encoding="utf-8") as file:
                    data = json.load(file)
                self._pruned_total = int(data.get("pruned_total") or 0)
        except Exception as err:
            logger.warning(f"读取清理统计失败：{err}")
            self._pruned_total = 0

    def __save_stats(self):
        with self._stats_lock:
            try:
                tmp_path = f"{self._stats_json}.tmp"
                with open(tmp_path, "w", encoding="utf-8") as file:
                    json.dump({"pruned_total": int(self._pruned_total)}, file, ensure_ascii=False)
                os.replace(tmp_path, self._stats_json)
            except OSError as err:
                logger.warning(f"保存清理统计失败：{err}")

    def __bump_pruned(self, count: int):
        if not count or count <= 0:
            return
        with self._stats_lock:
            self._pruned_total += int(count)
        self.__save_stats()

    def __current_saved_config(self) -> dict:
        """读取宿主当前保存的插件配置，隔离环境下不可用时返回空字典。"""
        try:
            config = self.get_config()
            return dict(config) if isinstance(config, dict) else {}
        except Exception:
            return {}

    def __staged_snapshot(self) -> dict:
        with self._staged_lock:
            return dict(self._staged_config or {})

    @staticmethod
    def __effective_bool(key: str, saved: dict, staged: dict, default: bool = False) -> bool:
        if key in staged:
            return bool(staged[key])
        if key in saved:
            return bool(saved[key])
        return default

    def __effective_rules(self, saved: dict, staged: dict) -> List[dict]:
        if "_rules" in staged:
            return deepcopy(staged.get("_rules") or [])
        return self.__rules_from_config(saved)

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

    def __monitor_config_rows(self) -> List[Dict[str, Any]]:
        """把目录配置解析成页面可展示的映射行，不依赖插件是否已启用。"""
        rows: List[Dict[str, Any]] = []
        seen = set()
        for original_conf in str(self._monitor_confs or "").splitlines():
            monitor_conf = original_conf.strip()
            if not monitor_conf or monitor_conf.startswith("#"):
                continue
            line_monitor = None
            if monitor_conf.count("$") == 1:
                line_monitor = str(monitor_conf.split("$", 1)[1]).strip()
                monitor_conf = monitor_conf.split("$", 1)[0].strip()
            category = None
            if monitor_conf.count("@") == 1:
                category = str(monitor_conf.split("@", 1)[1]).strip()
                monitor_conf = monitor_conf.split("@", 1)[0].strip()
            if monitor_conf.count("#") < 3:
                continue
            local_dir, strm_dir, cloud_dir, format_str = monitor_conf.split("#", 3)
            local_dir = local_dir.strip()
            strm_dir = strm_dir.strip()
            cloud_dir = cloud_dir.strip()
            format_str = format_str.strip()
            if not local_dir or not strm_dir:
                continue
            key = (self.__path_key(local_dir), self.__path_key(strm_dir))
            if key in seen:
                continue
            seen.add(key)
            if line_monitor == "1":
                monitor_state = "监控中"
            elif line_monitor == "0":
                monitor_state = "已停用"
            elif self._enabled and self._monitor:
                monitor_state = "监控中"
            else:
                monitor_state = "已配置"
            rows.append({
                "category": category or "-",
                "state": monitor_state,
                "local_dir": local_dir,
                "strm_dir": strm_dir,
                "cloud_dir": cloud_dir or "-",
                "format_str": format_str or "-",
                "mounted": Path(local_dir).is_dir(),
            })
        return rows

    def __monitor_status(self) -> Tuple[str, str, str]:
        """返回监控状态、颜色和说明。"""
        rows = self.__monitor_config_rows()
        if not self._enabled:
            return "插件已停用", "default", "启用插件并保存配置后开始监控"
        if not rows:
            return "未配置目录", "warning", "请在“路径监控与 STRM 映射策略”中配置目录"
        mounted = sum(1 for row in rows if row.get("mounted"))
        if mounted == 0:
            return "CD2 挂载异常", "error", f"{len(rows)} 个监控目录均不可访问"
        if mounted < len(rows):
            return "CD2 部分异常", "warning", f"仅 {mounted}/{len(rows)} 个监控目录可访问"
        if not self._monitor:
            return "已启用（未开启实时监控）", "info", "可开启 OpenList + CD2 实时监控"
        return "OpenList + CD2 监控中", "success", f"{len(rows)} 个 CD2 目录正常"

    def __openlist_status(self) -> Tuple[str, str, str]:
        """根据目录模板判断 OpenList 地址是否已配置。"""
        templates = [row.get("format_str", "") for row in self.__monitor_config_rows()]
        if not templates:
            return "OpenList 未配置", "warning", "目录模板中未发现地址"
        if any(("http://" in template or "https://" in template) for template in templates):
            return "OpenList 已配置", "success", f"{len(templates)} 个地址模板"
        return "OpenList 未配置", "warning", "目录模板应包含 http(s) 地址"



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
        # V1.4.0：任务结束写入实时事件流，供页面 Live Log Feed 展示
        finished_stats = (finished or {}).get("stats") or {}
        kind_names = {"full_scan": "全量扫描", "targeted": "定向同步", "retry": "失败重试"}
        status_names = {"success": "成功", "partial": "部分成功", "failed": "失败", "interrupted": "已中断"}
        self.__log_event(
            "TASK",
            f"{kind_names.get((finished or {}).get('kind'), '任务')}"
            f"{status_names.get((finished or {}).get('status'), '结束')}："
            f"成功 {finished_stats.get('success', 0)}，跳过 {finished_stats.get('skipped', 0)}，"
            f"失败 {finished_stats.get('failed', 0)}")

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

    # V1.4.0：页面可直接切换的策略开关白名单及其默认值
    _config_toggle_keys = {
        "monitor": "OpenList + CD2 实时监控",
        "cron_enabled": "定时增量扫描",
        "sync_delete": "云端同步删除",
        "cover": "覆盖已存在文件",
        "copy_files": "复制旁车文件",
        "copy_subtitles": "复制字幕文件",
        "notify": "任务与入库通知",
    }
    _config_toggle_defaults = {"cron_enabled": True}

    def __api_config_toggle(self, payload: Optional[dict] = Body(default=None)):
        """页面开关：服务端翻转指定布尔配置并写入暂存，保存后生效。"""
        key = str((payload or {}).get("key") or "").strip()
        if key not in self._config_toggle_keys:
            return self.__api_error(400, f"不支持切换的配置项：{key}")
        saved = self.__current_saved_config()
        with self._staged_lock:
            staged = dict(self._staged_config or {})
            if key in staged:
                current = bool(staged[key])
            elif key in saved:
                current = bool(saved[key])
            else:
                current = bool(self._config_toggle_defaults.get(key, False))
            staged[key] = not current
            self._staged_config = staged
            new_value = staged[key]
        label = self._config_toggle_keys.get(key, key)
        self.__log_event("CONFIG", f"{label} 已{'开启' if new_value else '关闭'}（待保存）")
        return {"key": key, "value": new_value, "staged": True}

    def __api_config_save(self, payload: Optional[dict] = Body(default=None)):
        """把页面暂存的开关、映射删除和扩展名变更落盘并重新初始化插件。"""
        with self._staged_lock:
            staged = dict(self._staged_config or {})
        if not staged:
            return {"saved": False, "message": "没有待保存的更改"}
        saved = self.__current_saved_config()
        new_config = dict(saved)
        rules = staged.pop("_rules", None)
        for key, value in staged.items():
            if key in self._config_toggle_keys or key == "rmt_mediaext":
                new_config[key] = value
        if rules is not None:
            slots = max(len(rules), self.__count_rule_slots(saved))
            new_config.update(self.__rules_to_config_keys(rules, slots))
            new_config["monitor_confs"] = self.__rules_to_monitor_confs(rules)
        try:
            self.update_config(new_config)
        except Exception as err:
            return self.__api_error(500, f"保存配置失败：{err}")
        with self._staged_lock:
            self._staged_config = None
        self._page_editing_rule = None
        self.__log_event("CONFIG", "配置已保存，OpenList + CD2 监控服务重新加载")
        try:
            self.init_plugin(new_config)
        except Exception as err:
            logger.error(f"保存配置后重新初始化失败：{err} - {traceback.format_exc()}")
        return {"saved": True}

    def __api_config_discard(self, payload: Optional[dict] = Body(default=None)):
        with self._staged_lock:
            had_changes = bool(self._staged_config)
            self._staged_config = None
        self._page_editing_rule = None
        return {"discarded": had_changes}

    def __api_mapping_delete(self, payload: Optional[dict] = Body(default=None)):
        """删除一条映射规则，变更写入暂存，点击「保存配置」后生效。"""
        try:
            index = int((payload or {}).get("index"))
        except (TypeError, ValueError):
            return self.__api_error(400, "index 必须是数字")
        saved = self.__current_saved_config()
        with self._staged_lock:
            staged = dict(self._staged_config or {})
            rules = deepcopy(staged["_rules"]) if "_rules" in staged \
                else self.__rules_from_config(saved)
            if index < 0 or index >= len(rules):
                return self.__api_error(404, f"映射规则不存在：第 {index + 1} 条")
            removed = rules.pop(index)
            staged["_rules"] = rules
            self._staged_config = staged
        removed_name = removed.get("category") or removed.get("local") or f"第 {index + 1} 条"
        self.__log_event("CONFIG", f"映射规则「{removed_name}」已标记删除（待保存）")
        return {"deleted": index, "remaining": len(rules), "staged": True}

    def __api_mapping_edit(self, payload: Optional[dict] = Body(default=None)):
        """标记正在编辑的规则行，页面展开「前往设置编辑」提示；再次点击取消。"""
        try:
            index = int((payload or {}).get("index", -1))
        except (TypeError, ValueError):
            return self.__api_error(400, "index 必须是数字")
        if self._page_editing_rule == index:
            self._page_editing_rule = None
            editing = None
        else:
            self._page_editing_rule = index
            editing = index
        return {"editing": editing,
                "message": "映射规则的新增与编辑请在插件「设置 → 路径监控与 STRM 映射策略」中完成"}

    def __api_extension_remove(self, payload: Optional[dict] = Body(default=None)):
        """从监控扩展名列表移除一个格式，变更写入暂存。"""
        ext = str((payload or {}).get("ext") or "").strip().lower()
        if not ext:
            return self.__api_error(400, "ext 不能为空")
        if not ext.startswith("."):
            ext = "." + ext
        saved = self.__current_saved_config()
        with self._staged_lock:
            staged = dict(self._staged_config or {})
            current_value = (staged.get("rmt_mediaext") or saved.get("rmt_mediaext")
                             or self._default_rmt_mediaext)
            extensions = sorted(self.__normalise_extensions(current_value,
                                                            self._default_rmt_mediaext))
            if ext not in extensions:
                return self.__api_error(404, f"扩展名不存在：{ext}")
            if len(extensions) <= 1:
                return self.__api_error(400, "至少保留一种视频格式")
            extensions.remove(ext)
            staged["rmt_mediaext"] = ", ".join(extensions)
            self._staged_config = staged
        self.__log_event("CONFIG", f"监控扩展名 {ext} 已移除（待保存）")
        return {"removed": ext, "extensions": extensions, "staged": True}

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
        # V1.4.0：定时增量扫描与页面暂存状态
        self._cron_enabled = True
        self._scan_interval = 30
        with self._staged_lock:
            self._staged_config = None
        self._page_editing_rule = None
        self._stats_json = os.path.join(self.get_data_path(), "stats.json")
        self._pruned_total = 0
        self.__load_stats()

        if config:
            self._enabled = bool(config.get("enabled"))
            self._onlyonce = bool(config.get("onlyonce"))
            self._interval = config.get("interval") or 10
            self._monitor = bool(config.get("monitor"))
            # V1.4.0：定时增量扫描开关与周期（分钟）
            self._cron_enabled = bool(config.get("cron_enabled", True))
            try:
                self._scan_interval = max(5, int(config.get("scan_interval") or 30))
            except (TypeError, ValueError):
                self._scan_interval = 30
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
            # V1.4.0：存在结构化映射规则时以其为准，序列化为旧版文本走原有解析
            if self.__count_rule_slots(config):
                rules = self.__rules_from_config(config)
                self._monitor_confs = self.__rules_to_monitor_confs(rules)
                # 旧版文本镜像与结构化规则保持一致，便于降级回滚与备份
                if str(config.get("monitor_confs") or "") != self._monitor_confs:
                    try:
                        mirror_config = dict(config)
                        mirror_config["monitor_confs"] = self._monitor_confs
                        self.update_config(mirror_config)
                    except Exception:
                        pass
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

            # V1.4.0：定时增量扫描，对应设计稿「定时增量扫描」开关
            if self._enabled and self._cron_enabled and self._strm_dir_conf:
                self._scheduler.add_job(
                    func=self.__scheduled_scan, trigger='interval',
                    minutes=self._scan_interval,
                    name="CloudStrm定时增量扫描")
                logger.info(f"定时增量扫描已启动，周期 {self._scan_interval} 分钟")

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __scheduled_scan(self):
        """定时增量扫描入口：记录轮询事件并复用统一任务执行器。"""
        self.__log_event("POLL", f"定时增量扫描启动（周期 {self._scan_interval} 分钟），轮询 CD2 挂载目录")
        try:
            result = self.scan()
        except Exception as err:
            self.__log_event("FAIL", f"定时增量扫描异常：{err}")
            return
        if isinstance(result, dict) and not result.get("accepted", True):
            self.__log_event("POLL", "已有任务运行中，本次定时扫描跳过")

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
        # V1.4.0：实时监控事件写入 Live Log Feed
        self.__log_event("MONITOR", f"发现文件变更 -> {event_path}")
        result = self.__handle_file(event_path=event_path, mon_path=mon_path)
        if not result:
            return
        target_file = result.get("target_file") or ""
        if result.get("status") == "success" and str(target_file).lower().endswith(".strm"):
            self.__log_event("STRM-GEN", f"生成文件 -> {target_file}")
        elif result.get("status") == "failed":
            self.__log_event("FAIL", f"{event_path} 处理失败：{result.get('reason') or '未知原因'}")

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
            self.__log_event("POLL", f"目录变更，增量扫描 -> {event_path}")
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
        removed_count = 0
        for candidate in candidates:
            if self.__remove_file_if_generated(str(candidate)):
                removed_count += 1
        removed = removed_count > 0
        # V1.4.0：死链清理计数与实时事件
        if removed_count:
            self.__bump_pruned(removed_count)
            self.__log_event("PRUNE", f"云端源文件已删除，同步清理 {removed_count} 个本地文件 <- {event_path}")
        else:
            self.__log_event("PRUNE", f"未发现死链，跳过清理动作 <- {event_path}")
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
            mon_categories = CloudStrmHelper.__category_list(mon_category)
            requested_categories = CloudStrmHelper.__category_list(category) if category else []
            category_matched = bool(
                requested_categories and any(tag in mon_categories for tag in requested_categories)
            ) or bool(category and str(category) in str(mon_category))
            if category and category_matched:
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
            elif not category and any(tag == str(args).strip() for tag in mon_categories):
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
            "cron_enabled": self._cron_enabled,
            "scan_interval": self._scan_interval,
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
            {
                "path": "/config/toggle",
                "endpoint": self.__api_config_toggle,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "切换 CloudStrm 策略开关（暂存）",
            },
            {
                "path": "/config/save",
                "endpoint": self.__api_config_save,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "保存 CloudStrm 页面暂存配置",
            },
            {
                "path": "/config/discard",
                "endpoint": self.__api_config_discard,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "放弃 CloudStrm 页面暂存配置",
            },
            {
                "path": "/mappings/delete",
                "endpoint": self.__api_mapping_delete,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "删除 CloudStrm 映射规则（暂存）",
            },
            {
                "path": "/mappings/edit",
                "endpoint": self.__api_mapping_edit,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "标记 CloudStrm 映射规则编辑入口",
            },
            {
                "path": "/extensions/remove",
                "endpoint": self.__api_extension_remove,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "移除 CloudStrm 监控扩展名（暂存）",
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

        def panel(title, content, icon=None):
            title_view = {"component": "VExpansionPanelTitle"}
            if icon:
                title_view["content"] = [
                    {"component": "VIcon", "props": {"icon": icon, "size": "small",
                                                      "class": "mr-2"}},
                    {"component": "span", "text": title},
                ]
            else:
                title_view["text"] = title
            return {"component": "VExpansionPanel", "content": [
                title_view,
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
                "text": "目录模板必须包含 {local_file} 或 {cloud_file}；保存后会立即校验，错误会显示在页面顶部。",
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
            "props": {"type": "info", "variant": "tonal"},
            "html": ("监控方式为 OpenList + CD2；移动云盘无官方 API，不提供网盘 API 轮询。<br>"
                     "按规则卡片填写：CD2 挂载目录 → STRM 生成目录 → OpenList 云盘目录 → STRM 模板，"
                     "模板必须包含 <code>{local_file}</code> 或 <code>{cloud_file}</code>。<br>"
                     "示例模板：<code>http://192.168.1.10:5244/d{cloud_file}</code><br>"
                     "旧版 <code>#</code> 分隔文本配置仍兼容读取，保存后自动迁移为规则卡片。"),
        }
        directory_content = [config_help, template_warning]
        monitor_way_alert = {
            "component": "VAlert",
            "props": {
                "type": "info", "variant": "tonal", "density": "compact", "class": "mb-3",
                "text": "监控方式：OpenList + CD2。移动云盘无官方 API，插件通过 CD2 挂载目录发现文件变化，STRM 内容使用 OpenList 地址模板。",
            },
        }
        # V1.4.0：结构化映射规则编辑器，运行时配置已由 init_plugin 归一化为旧版文本
        form_rules = self.__rules_from_monitor_confs(self._monitor_confs)
        rule_slot_count = min(12, max(4, len(form_rules) + 2))
        rule_cards = []
        for rule_index in range(rule_slot_count):
            rule_cards.append({
                "component": "VCard",
                "props": {"variant": "tonal", "class": "mb-3"},
                "content": [{
                    "component": "VCardText", "content": [
                        {"component": "div",
                         "props": {"class": "text-caption text-medium-emphasis mb-1"},
                         "text": f"映射规则 {rule_index + 1}"},
                        row(
                            col({
                                "component": "VCombobox",
                                "props": {
                                    "model": f"rule_{rule_index}_category",
                                    "label": "分类标签",
                                    "multiple": True,
                                    "chips": True,
                                    "smallChips": True,
                                    "density": "compact",
                                    "items": ["电影", "电视剧", "国产剧", "港剧", "台剧",
                                              "美剧", "韩剧", "日剧", "综艺", "动漫", "纪录片"],
                                    "placeholder": "输入后回车添加",
                                },
                            }, 4),
                            col(switch(f"rule_{rule_index}_monitor", "实时监控"), 2),
                            col(field("VTextField", f"rule_{rule_index}_local",
                                      "CD2 挂载目录（MoviePilot 中路径）",
                                      placeholder="/mnt/media", density="compact"), 4),
                            col(field("VTextField", f"rule_{rule_index}_strm", "STRM 生成目录",
                                      placeholder="/mnt/library", density="compact"), 4),
                        ),
                        row(
                            col(field("VTextField", f"rule_{rule_index}_cloud", "OpenList 云盘目录",
                                      placeholder="/移动网盘/媒体库/电影", density="compact"), 6),
                            col(field("VTextField", f"rule_{rule_index}_format", "STRM 格式化模板",
                                      placeholder="http://192.168.1.10:5244/d{cloud_file}",
                                      density="compact"), 6),
                        ),
                    ],
                }],
            })
        directory_content.extend(rule_cards)
        directory_content.extend([
            row(col(field("VTextarea", "emby_path", "媒体库路径映射", rows=2,
                         placeholder="本地路径=>Emby路径，多组用英文逗号分隔"), 6),
                col(field("VTextarea", "path_replacements", "STRM 路径替换规则", rows=3,
                         placeholder="源路径=>目标路径，每行一条；兼容旧版冒号格式"), 6)),
        ])
        # 配置错误提示固定在表单顶部常显，避免被折叠面板遮挡
        form_content = []
        if self._config_errors:
            form_content.append(config_error_alert)
        form_content.append(monitor_way_alert)
        form_content.append({
            "component": "VExpansionPanels",
            "props": {"variant": "accordion", "multiple": True, "model": "_panel_open"},
            "content": [
                panel("基础设置", [
                    row(col(switch("enabled", "启用插件"), 3),
                        col(switch("monitor", "OpenList + CD2 实时监控"), 3),
                        col(switch("cron_enabled", "定时增量扫描"), 3),
                        col(switch("notify", "任务与入库通知"), 3)),
                    row(col(switch("onlyonce", "保存后立即执行一次"), 3),
                        col(field("VTextField", "interval", "入库通知延迟（秒）",
                                 type="number", min=1, placeholder="10"), 4),
                        col(field("VTextField", "scan_interval", "定时增量扫描周期（分钟）",
                                 type="number", min=5, placeholder="30"), 5)),
                ], "mdi-cog"),
                panel("文件处理", [
                    row(col(switch("cover", "覆盖已存在文件"), 3),
                        col(switch("copy_files", "复制旁车文件"), 3),
                        col(switch("copy_subtitles", "复制字幕文件"), 3),
                        col(switch("sync_delete", "同步删除生成文件"), 3)),
                ], "mdi-file-sync"),
                panel("路径监控与 STRM 映射策略", [
                    *directory_content,
                ], "mdi-folder-sync"),
                panel("媒体格式", [
                    row(col(field("VTextarea", "rmt_mediaext", "视频格式", rows=2,
                                 placeholder=self._default_rmt_mediaext), 6),
                        col(field("VTextarea", "other_mediaext", "非媒体格式", rows=2,
                                 placeholder=self._default_other_mediaext), 6)),
                ], "mdi-format-list-bulleted"),
                panel("媒体库与高级设置", [
                    row(col({"component": "VSelect", "props": {
                        "multiple": True, "chips": True, "clearable": True,
                        "model": "mediaservers", "label": "Emby 媒体服务器", "items": emby_items,
                    }}, 6),
                        col(switch("refresh_emby", "生成后刷新 Emby"), 6)),
                    row(col(switch("uriencode", "云盘路径 URL 编码"), 4),
                        col(field("VTextField", "url", "任务推送 URL",
                                  placeholder="POST JSON：path、type=add"), 8)),
                ], "mdi-server"),
            ],
        })
        form = [{
            "component": "VForm",
            "content": form_content,
        }]
        model = {
            "enabled": False, "notify": False, "monitor": False, "cover": False,
            "onlyonce": False, "copy_files": False, "uriencode": False,
            "copy_subtitles": False, "sync_delete": False, "refresh_emby": False,
            "mediaservers": [], "emby_path": "",
            "interval": 10, "url": "",
            "other_mediaext": self._default_other_mediaext,
            "rmt_mediaext": self._default_rmt_mediaext, "path_replacements": "",
            # V1.4.0：定时增量扫描与结构化映射规则默认值
            "cron_enabled": True, "scan_interval": 30,
            # 界面状态：折叠面板展开组，有配置错误时自动展开「目录映射」
            "_panel_open": [0, 2] if self._config_errors else [0],
        }
        for rule_index in range(rule_slot_count):
            rule = form_rules[rule_index] if rule_index < len(form_rules) else {}
            model[f"rule_{rule_index}_category"] = self.__category_list(
                rule.get("category", ""))
            model[f"rule_{rule_index}_local"] = rule.get("local", "")
            model[f"rule_{rule_index}_strm"] = rule.get("strm", "")
            model[f"rule_{rule_index}_cloud"] = rule.get("cloud", "")
            model[f"rule_{rule_index}_format"] = rule.get("format", "")
            model[f"rule_{rule_index}_monitor"] = rule.get("monitor", True)
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

        status_colors = {
            "running": "info", "success": "success", "partial": "warning",
            "failed": "error", "interrupted": "grey",
        }

        def chip(text, color="default"):
            return {"component": "VChip", "props": {"size": "small", "color": color,
                                                       "variant": "tonal"}, "text": text}

        # 最近任务：富列表呈现，状态带颜色，行内直接打开详情，最多展示 10 条
        task_item_views = []
        for task in summaries[:10]:
            task_id_value = task.get("id")
            if not task_id_value:
                continue
            task_status = task.get("status") or ""
            related_retries = retry_relations.get(task_id_value) or []
            task_time = str(task.get('finished_at') or task.get('created_at') or '-')
            task_duration = task.get('duration_seconds', 0) or 0
            task_item_views.append({
                "component": "VRow",
                "props": {"align": "center", "noGutters": True,
                          "class": "py-1 task-row",
                          "style": "border-bottom:1px solid rgba(55,65,81,.25);"},
                "content": [
                    {"component": "VCol", "props": {"cols": 2, "class": "text-left text-caption"},
                     "content": [{"component": "span",
                                  "text": kind_names.get(task.get('kind'), task.get('kind'))}]},
                    {"component": "VCol", "props": {"cols": 3, "class": "text-left text-caption"},
                     "content": [{"component": "span",
                                  "props": {"class": "text-truncate", "title": task_time},
                                  "text": task_time}]},
                    {"component": "VCol", "props": {"cols": 2, "class": "text-left"},
                     "content": [chip(status_names.get(task_status, task_status),
                                      status_colors.get(task_status, "default"))]},
                    {"component": "VCol", "props": {"cols": 1, "class": "text-left text-caption"},
                     "content": [{"component": "span",
                                  "text": f"{len(related_retries)}" + ("重试" if related_retries else "")}]},
                    {"component": "VCol", "props": {"cols": 1, "class": "text-left text-caption"},
                     "content": [{"component": "span", "text": f"{task_duration:.1f}s"}]},
                    {"component": "VCol", "props": {"cols": 2, "class": "text-left text-caption"},
                     "content": [{"component": "span",
                                  "props": {"class": "text-truncate", "title": task_id_value},
                                  "text": task_id_value}]},
                    {"component": "VCol", "props": {"cols": 1, "class": "text-right"},
                     "content": [{
                         "component": "VBtn",
                         "props": {"prependIcon": "mdi-file-document-outline", "size": "x-small",
                                   "variant": "tonal"},
                         "text": "详情",
                         "events": {"click": {"api": f"plugin/{self.__class__.__name__}/tasks/{task_id_value}",
                                              "method": "GET", "params": {}}},
                     }]},
                ],
            })
        if task_item_views:
            recent_body = [{
                "component": "div",
                "props": {"class": "task-list", "style": "width:100%;"},
                "content": task_item_views,
            }]
        else:
            recent_body = [{
                "component": "VAlert",
                "props": {"type": "info", "variant": "tonal",
                          "text": "暂无任务记录，点击上方「立即全量扫描」开始第一个任务。"},
            }]
        # 顶部状态区：运行中展示实时进度与当前统计，空闲时展示最近一次任务结果
        is_running = bool(current)
        current_label = status_names.get(current.get("status"), "空闲") if is_running else "空闲"
        current_color = status_colors.get(current.get("status"), "default") if is_running else "default"
        current_total = max(1, current_stats.get("discovered", 0))
        current_progress = min(100, round(current_stats.get("processed", 0) * 100 / current_total)) if is_running else 0
        last_finished = None if is_running else next(
            (task for task in summaries if task.get("status") != "running"), None)
        overview_stats = current_stats if is_running else ((last_finished or {}).get("stats") or {})
        overview_rows = [{
            "component": "VRow",
            "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 3},
                 "content": [chip(f"当前任务：{current_label}", current_color)]},
            ] + ([{
                "component": "VCol", "props": {"cols": 12, "md": 9},
                "content": [{"component": "VProgressLinear", "props": {
                    "modelValue": current_progress, "height": 8, "rounded": True,
                    "color": "primary",
                    "indeterminate": not bool(current_stats.get("discovered"))}}]},
            ] if is_running else []),
        }]
        def stat_box(label, value, value_color="primary"):
            return {
                "component": "VCol", "props": {"cols": 6, "sm": 4, "md": 2, "class": "pa-1"},
                "content": [{"component": "div", "html": (
                    "<div style=\"background:#1f2937;border:1px solid #374151;border-radius:8px;"
                    "padding:8px 10px;text-align:center;height:100%;box-sizing:border-box;\">"
                    f"<div style=\"color:#9ca3af;font-size:10px;white-space:nowrap;overflow:hidden;"
                    f"text-overflow:ellipsis;\">{html_escape(label)}</div>"
                    f"<div style=\"color:{value_color};font-size:16px;font-weight:700;line-height:1.4;"
                    f"white-space:nowrap;\">{html_escape(str(value))}</div></div>"
                )}],
            }

        if is_running or last_finished:
            overview_rows.append({
                "component": "VRow",
                "content": ([{
                  "component": "VCol", "props": {"cols": 6, "md": 2},
                    "content": [{"component": "div",
                                  "props": {"class": "text-caption text-medium-emphasis text-center pa-2"},
                                  "text": "最近任务结果"}]
                }] if not is_running else []) + [
                    stat_box("总数", overview_stats.get('discovered', 0), "#38bdf8"),
                    stat_box("已处理", overview_stats.get('processed', 0), "#38bdf8"),
                    stat_box("成功", overview_stats.get('success', 0), "#10b981"),
                    stat_box("跳过", overview_stats.get('skipped', 0), "#f59e0b"),
                    stat_box("失败", overview_stats.get('failed', 0), "#f43f5e"),
                ],
            })
        latest_id = self._page_task_id or (current.get("id") if current else (summaries[0].get("id") if summaries else ""))
        latest_task = self.__get_task(latest_id) if latest_id else None
        latest_items = (latest_task or {}).get("items") or []
        if self._page_filter_status:
            latest_items = [item for item in latest_items
                            if item.get("status") == self._page_filter_status]
        items_total = len(latest_items)
        latest_items = latest_items[:100]
        item_rows = []
        retryable_failed_ids = []
        for item in latest_items:
            item_status = item.get("status") or ""
            if item_status == "failed" and item.get("retryable"):
                retryable_failed_ids.append(item.get("id"))
            item_rows.append({
                "来源": self.__shorten_path(item.get("source_file") or ""),
                "目标": self.__shorten_path(item.get("target_file") or ""),
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
        if failed_item_views:
            failed_block = {
                "component": "VList", "props": {"density": "compact", "lines": "three"},
                "content": failed_item_views,
            }
        else:
            failed_block = {
                "component": "VAlert",
                "props": {"type": "success", "variant": "tonal",
                          "text": "本次任务没有可重试的失败项。"},
            }
        # 筛选按钮选中态由服务端状态驱动：当前筛选高亮，其余为文字按钮
        detail_filters = []
        active_filter = self._page_filter_status or ""
        for filter_status, filter_label in (("", "全部"), ("success", "成功"),
                                             ("skipped", "跳过"), ("failed", "失败")):
            is_active_filter = filter_status == active_filter
            filter_props = {"size": "small", "disabled": not bool(detail_url),
                            "variant": "flat" if is_active_filter else "text",
                            "prependIcon": "mdi-filter-variant" if filter_status else "mdi-filter-off-outline"}
            if is_active_filter:
                filter_props["color"] = "primary"
            detail_filters.append({
                "component": "VBtn",
                "props": filter_props,
                "text": filter_label,
                "events": {"click": {"api": detail_url, "method": "GET",
                                             "params": ({"status": filter_status} if filter_status else {})}},
             })
        monitor_rows = self.__monitor_config_rows()
        monitor_status, monitor_color, monitor_detail = self.__monitor_status()
        openlist_status, openlist_color, openlist_detail = self.__openlist_status()
        strm_total = len(self._generated_files)
        failed_total = overview_stats.get("failed", 0)
        skipped_total = overview_stats.get("skipped", 0)
        tasks_url = f"plugin/{self.__class__.__name__}/tasks"

        # ---------- V1.4.0：参考设计稿的深色监控台（OpenList + CD2 口径） ----------
        toggle_url = f"plugin/{self.__class__.__name__}/config/toggle"
        save_url = f"plugin/{self.__class__.__name__}/config/save"
        discard_url = f"plugin/{self.__class__.__name__}/config/discard"
        mapping_delete_url = f"plugin/{self.__class__.__name__}/mappings/delete"
        mapping_edit_url = f"plugin/{self.__class__.__name__}/mappings/edit"
        extension_remove_url = f"plugin/{self.__class__.__name__}/extensions/remove"
        saved_config = self.__current_saved_config()
        staged_config = self.__staged_snapshot()
        staged_dirty = bool(staged_config)
        status_dot_colors = {"success": "#10b981", "warning": "#f59e0b", "error": "#f43f5e",
                             "info": "#38bdf8", "default": "#6b7280"}
        dark_card_style = ("background:#111827;border:1px solid #1f2937;"
                           "border-radius:10px;color:#e5e7eb;")

        def panel_title(title, subtitle=""):
            subtitle_html = (f"<div style=\"color:#9ca3af;font-size:12px;margin-top:2px;\">"
                             f"{html_escape(subtitle)}</div>" if subtitle else "")
            return (f"<div style=\"color:#f9fafb;font-size:15px;font-weight:600;\">"
                    f"{html_escape(title)}</div>" + subtitle_html)

        def metric_card(title, value, unit, value_color):
            return {
                "component": "VCol", "props": {"cols": 6},
                "content": [{"component": "div", "html": (
                    "<div style=\"background:#1f2937;border-radius:8px;padding:10px 12px;\">"
                    f"<div style=\"color:#9ca3af;font-size:11px;\">{html_escape(title)}</div>"
                    f"<div style=\"color:{value_color};font-size:20px;font-weight:700;line-height:1.4;\">"
                    f"{html_escape(str(value))}"
                    f"<span style=\"color:#9ca3af;font-size:10px;font-weight:400;\">"
                    f" {html_escape(unit)}</span></div></div>"
                )}],
            }

        def hint_box(html_text):
            return {"component": "div", "html": (
                "<div style=\"border:1px solid rgba(2,132,199,.45);background:rgba(2,132,199,.12);"
                f"color:#7dd3fc;border-radius:8px;padding:8px 12px;font-size:12px;\">{html_text}</div>"
            )}

        def strategy_row(label, subtitle, key):
            """设计稿同款策略开关行：点击即暂存翻转，「保存配置」后生效。"""
            effective = self.__effective_bool(key, saved_config, staged_config,
                                              self._config_toggle_defaults.get(key, False))
            pending_tag = (
                "<span style=\"color:#f59e0b;font-size:10px;margin-left:6px;border:1px solid #f59e0b;"
                "border-radius:4px;padding:0 4px;\">待保存</span>" if key in staged_config else "")
            label_html = (
                f"<div style=\"color:#e5e7eb;font-size:13px;\">{html_escape(label)}{pending_tag}</div>"
                f"<div style=\"color:#9ca3af;font-size:11px;margin-top:2px;\">{html_escape(subtitle)}</div>"
            )
            return {
                "component": "VRow",
                "props": {"align": "center", "noGutters": True, "class": "py-2"},
                "content": [
                    {"component": "VCol", "props": {"cols": 9},
                     "content": [{"component": "div", "html": label_html}]},
                    {"component": "VCol", "props": {"cols": 3, "class": "d-flex justify-end"},
                     "content": [{
                         "component": "VSwitch",
                         "props": {"modelValue": effective, "color": "primary", "inset": True,
                                   "hideDetails": True, "density": "compact"},
                         "events": {"click": {"api": toggle_url, "method": "POST",
                                              "params": {"key": key}}},
                     }]},
                ],
            }

        def row_divider():
            return {"component": "div",
                    "html": "<div style=\"border-top:1px solid #1f2937;\"></div>"}

        def rule_state(rule):
            local_dir = rule.get("local") or ""
            format_str = rule.get("format") or ""
            if local_dir and not Path(local_dir).is_dir():
                return "目录不可访问", "#f43f5e"
            if format_str and not any(token in format_str
                                      for token in ("{local_file}", "{cloud_file}")):
                return "模板缺占位符", "#f59e0b"
            if not rule.get("monitor", True):
                return "实时已停用", "#9ca3af"
            if self._enabled and self._monitor:
                return "监控中", "#10b981"
            return "已配置", "#38bdf8"

        def mapping_rule_html(rule, state_text, state_color, extra_style=""):
            category_tags = CloudStrmHelper.__category_list(rule.get("category")) or ["未分类"]
            category_badges = "".join(
                f"<span style=\"flex:0 0 auto;background:#1e293b;border:1px solid #3b82f6;"
                f"color:#38bdf8;border-radius:4px;padding:3px 8px;font-size:11px;font-weight:600;"
                f"white-space:nowrap;margin-right:4px;\">{html_escape(tag)}</span>"
                for tag in category_tags
            )
            strm_dir = html_escape(rule.get("strm") or "-")
            cloud_dir = html_escape(rule.get("cloud") or "-")
            return (
                "<div style=\"display:flex;align-items:center;gap:10px;padding:10px 12px;"
                "border:1px solid rgba(55,65,81,.55);border-radius:10px;"
                f"background:rgba(55,65,81,.22);{extra_style}\">"
                "<span style=\"display:flex;flex:0 0 auto;align-items:center;flex-wrap:wrap;gap:2px;\">"
                f"{category_badges}</span>"
                "<div style=\"flex:1 1 auto;min-width:0;font-family:Consolas,Monaco,monospace;\">"
                f"<div style=\"color:#e5e7eb;font-size:12px;white-space:nowrap;overflow:hidden;"
                f"text-overflow:ellipsis;\" title=\"{strm_dir}\">{strm_dir}</div>"
                f"<div style=\"color:#6b7280;font-size:11px;white-space:nowrap;overflow:hidden;"
                f"text-overflow:ellipsis;\" title=\"{cloud_dir}\">➜ {cloud_dir}</div></div>"
                f"<span style=\"flex:0 0 auto;color:{state_color};font-size:11px;"
                f"white-space:nowrap;\">{html_escape(state_text)}</span></div>"
            )

        # 头部：标题 + 状态徽章 + 操作按钮（对应设计稿 Header Bar）
        header_title_html = (
            "<div style=\"display:flex;align-items:center;gap:12px;\">"
            "<div style=\"width:36px;height:36px;border-radius:8px;background:#0284c7;"
            "display:flex;align-items:center;justify-content:center;flex:0 0 auto;\">"
            "<svg width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\">"
            "<path d=\"M6.5 19h11a4.5 4.5 0 0 0 .9-8.9A6 6 0 0 0 6.8 8.2 5.5 5.5 0 0 0 6.5 19z\""
            " fill=\"#ffffff\" opacity=\"0.95\"/><circle cx=\"17.5\" cy=\"6.5\" r=\"2.2\" fill=\"#38bdf8\"/>"
            "</svg></div>"
            "<div style=\"min-width:0;\">"
            "<div style=\"color:#f9fafb;font-size:17px;font-weight:600;line-height:1.35;\">"
            "中国移动云盘 STRM 助手</div>"
            "<div style=\"color:#9ca3af;font-size:12px;\">"
            "精简高性能 · 自动化 STRM 生成与 MP 联动 · OpenList + CD2</div>"
            "</div></div>"
        )
        header_chips = [
            chip(f"OpenList + CD2 · {monitor_status.replace('OpenList + CD2 ', '', 1)}",
                 monitor_color),
            chip(openlist_status, openlist_color),
        ]
        if staged_dirty:
            header_chips.append(chip("有未保存更改", "warning"))
        for header_chip in header_chips:
            header_chip["props"]["class"] = "ma-1"
        header_button_cols = [
            {"component": "VCol", "props": {"cols": "auto"},
             "content": [{
                 "component": "VBtn",
                 "props": {"prependIcon": "mdi-text-box-search-outline", "size": "small",
                           "variant": "flat", "style": "background:#374151;color:#e5e7eb;"},
                 "text": "查看日志",
                 "events": {"click": {"api": tasks_url, "method": "GET", "params": {}}},
             }]},
            {"component": "VCol", "props": {"cols": "auto"},
             "content": [{
                 "component": "VBtn",
                 "props": {"prependIcon": "mdi-content-save", "size": "small", "variant": "flat",
                           "style": "background:#0284c7;color:#ffffff;",
                           "disabled": not staged_dirty},
                 "text": "保存配置",
                 "events": {"click": {"api": save_url, "method": "POST", "params": {}}},
             }]},
        ]
        if staged_dirty:
            header_button_cols.append({
                "component": "VCol", "props": {"cols": "auto"},
                "content": [{
                    "component": "VBtn",
                    "props": {"prependIcon": "mdi-undo-variant", "size": "small", "variant": "text",
                              "style": "color:#9ca3af;"},
                    "text": "放弃更改",
                    "events": {"click": {"api": discard_url, "method": "POST", "params": {}}},
                }],
            })
        header_card = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-4", "style": dark_card_style},
            "content": [
                {"component": "VCardText", "content": [
                    {"component": "VRow", "props": {"align": "center"}, "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 5},
                         "content": [{"component": "div", "html": header_title_html}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3},
                         "content": [{"component": "div", "content": header_chips}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4},
                         "content": [{"component": "VRow",
                                      "props": {"justify": "end", "align": "center"},
                                      "content": header_button_cols}]},
                    ]},
                ]},
            ],
        }

        # 左栏：账号与运行指标（本地 STRM 总数 / 孤儿清理死链计数 + OpenList+CD2 状态行）
        status_dot = status_dot_colors.get(monitor_color, "#6b7280")
        status_row_html = (
            "<div style=\"background:#1f2937;border:1px solid rgba(55,65,81,.5);border-radius:8px;"
            "padding:10px 12px;margin-top:4px;display:flex;align-items:center;gap:10px;\">"
            "<div style=\"flex:1 1 auto;min-width:0;\">"
            "<div style=\"color:#e5e7eb;font-size:12px;\">OpenList + CD2 运行状态</div>"
            f"<div style=\"color:#9ca3af;font-size:11px;\">"
            f"{html_escape(monitor_status)} · {html_escape(openlist_status)}</div></div>"
            f"<span style=\"width:8px;height:8px;border-radius:50%;background:{status_dot};"
            "flex:0 0 auto;\"></span></div>"
        )
        kpi_card = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-4", "style": dark_card_style},
            "content": [
                {"component": "VCardText", "content": [
                    {"component": "div", "html": panel_title("账号与运行指标")},
                    {"component": "VRow", "props": {"class": "mt-2"}, "content": [
                        metric_card("本地 STRM 总数", f"{strm_total:,}", "个", "#38bdf8"),
                        metric_card("孤儿清理（死链）", f"{self._pruned_total:,}", "个已删", "#f43f5e"),
                    ]},
                    {"component": "div", "html": status_row_html},
                    *([{"component": "VRow", "props": {"class": "mt-2"}, "content": [
                        {"component": "VCol", "props": {"cols": 12}, "content": [
                            {"component": "VProgressLinear", "props": {
                                "modelValue": current_progress, "height": 8, "rounded": True,
                                "color": "primary",
                                "indeterminate": not bool(current_stats.get("discovered"))}},
                        ]},
                    ]}] if is_running else []),
                    {"component": "div", "html": (
                        "<div style=\"color:#6b7280;font-size:11px;margin-top:10px;line-height:1.6;\">"
                        "移动云盘无官方 API：文件变化通过 CD2 挂载目录监控，STRM 内容使用 OpenList 地址模板。"
                        f"{html_escape(monitor_detail)} {html_escape(openlist_detail)}</div>"
                    )}
                ]},
            ],
        }

        # 左栏：自动化与清理策略（可用开关，点击暂存、保存生效）+ 扩展名标签 + 全量同步
        effective_exts = sorted(self.__normalise_extensions(
            staged_config.get("rmt_mediaext") or saved_config.get("rmt_mediaext")
            or self._default_rmt_mediaext, self._default_rmt_mediaext))
        ext_chip_views = []
        for ext in effective_exts:
            ext_chip_views.append({
                "component": "VChip",
                "props": {"size": "x-small", "variant": "outlined", "class": "ma-1",
                          "closable": len(effective_exts) > 1,
                          "style": "border-color:#3b82f6;color:#38bdf8;background:#1e293b;"},
                "text": ext,
                "events": {"click:close": {"api": extension_remove_url, "method": "POST",
                                           "params": {"ext": ext}}},
            })
        strategy_card = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-4", "style": dark_card_style},
            "content": [
                {"component": "VCardText", "content": [
                    {"component": "div", "html": panel_title("自动化与清理策略")},
                    strategy_row("监控 MoviePilot 整理入库",
                                 "CD2 挂载目录出现新文件（如 MP 整理完成）即刻生成 STRM", "monitor"),
                    row_divider(),
                    strategy_row("定时增量扫描",
                                 f"每 {self._scan_interval} 分钟主动轮询 CD2 挂载目录", "cron_enabled"),
                    row_divider(),
                    strategy_row("云端同步删除（Prune）",
                                 "网盘源文件被删时，同步清理本地 STRM", "sync_delete"),
                    {"component": "div", "html": (
                        "<div style=\"color:#e5e7eb;font-size:13px;font-weight:500;margin-top:14px;\">"
                        "监控扩展名限制</div>"
                    )},
                    {"component": "div", "content": ext_chip_views},
                    {"component": "div", "html": (
                        "<div style=\"color:#6b7280;font-size:11px;margin-bottom:10px;\">"
                        "点 × 移除（待保存）；新增格式请在插件设置中添加</div>"
                    )},
                    {
                        "component": "VBtn",
                        "props": {"block": True, "variant": "flat", "prependIcon": "mdi-sync",
                                  "style": "background:#0284c7;color:#ffffff;",
                                  "disabled": is_running},
                        "text": "立即全量同步（运行中）" if is_running else "立即全量同步",
                        "events": {"click": {"api": tasks_url, "method": "POST",
                                             "params": {"kind": "full_scan"}}},
                    },
                ]},
            ],
        }

        # 右栏：路径监控与 STRM 映射策略（分类徽章 + 路径对 + 编辑/删除）
        effective_rules = self.__effective_rules(saved_config, staged_config)
        pending_deleted_rules = []
        if "_rules" in staged_config:
            pending_deleted_rules = [rule for rule in self.__rules_from_config(saved_config)
                                     if rule not in effective_rules]
        mapping_row_views = []
        if self._page_editing_rule == -1:
            mapping_row_views.append(hint_box(
                "新增映射规则：请打开插件「设置 → 路径监控与 STRM 映射策略」，"
                "在空白规则卡片中填写后保存，本页会自动同步。"))
        for rule_index, rule in enumerate(effective_rules):
            state_text, state_color = rule_state(rule)
            mapping_row_views.append({
                "component": "VRow", "props": {"align": "center", "noGutters": True, "class": "mb-2"},
                "content": [
                    {"component": "VCol", "props": {"cols": 10},
                     "content": [{"component": "div",
                                  "html": mapping_rule_html(rule, state_text, state_color)}]},
                    {"component": "VCol", "props": {"cols": 2, "class": "d-flex justify-end"},
                     "content": [
                         {"component": "VBtn",
                          "props": {"icon": "mdi-pencil-outline", "size": "x-small",
                                     "variant": "text", "color": "info"},
                          "events": {"click": {"api": mapping_edit_url, "method": "POST",
                                               "params": {"index": rule_index}}}},
                         {"component": "VBtn",
                          "props": {"icon": "mdi-delete-outline", "size": "x-small",
                                     "variant": "text", "color": "error"},
                          "events": {"click": {"api": mapping_delete_url, "method": "POST",
                                               "params": {"index": rule_index}}}},
                     ]},
                ],
            })
            if self._page_editing_rule == rule_index:
                raw_line = self.__rules_to_monitor_confs([rule])
                mapping_row_views.append(hint_box(
                    "编辑映射规则：请在插件「设置 → 路径监控与 STRM 映射策略」的规则卡片中修改并保存。"
                    + (f"<br>当前规则原文：<code>{html_escape(raw_line)}</code>" if raw_line else "")))
        for rule in pending_deleted_rules:
            mapping_row_views.append({
                "component": "VRow", "props": {"noGutters": True, "class": "mb-2"},
                "content": [{"component": "VCol", "props": {"cols": 12},
                             "content": [{"component": "div", "html": mapping_rule_html(
                                 rule, "待删除 · 保存后生效", "#f59e0b", "opacity:.45;")}]}],
            })
        if not effective_rules and not pending_deleted_rules:
            mapping_row_views.append({"component": "div", "html": (
                "<div style=\"color:#6b7280;padding:18px 12px;text-align:center;font-size:13px;\">"
                "暂无映射规则，点击右上角「添加映射规则」开始配置</div>"
            )})
        mapping_card = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-4",
                      "style": dark_card_style + "flex-shrink:0;"},
            "content": [
                {"component": "VCardText", "content": [
                    {"component": "VRow", "props": {"align": "center", "noGutters": True},
                     "content": [
                         {"component": "VCol", "props": {"cols": 9}, "content": [
                             {"component": "div", "html": panel_title(
                                 "路径监控与 STRM 映射策略",
                                 f"本地 STRM 输出目录 → 移动云盘绝对路径 · 共 {len(effective_rules)} 条映射")}]},
                         {"component": "VCol", "props": {"cols": 3, "class": "d-flex justify-end"},
                          "content": [{
                              "component": "VBtn",
                              "props": {"prependIcon": "mdi-plus", "size": "small", "variant": "flat",
                                        "style": "background:#0284c7;color:#ffffff;"},
                              "text": "添加映射规则",
                              "events": {"click": {"api": mapping_edit_url, "method": "POST",
                                                   "params": {"index": -1}}}},
                          ]},
                     ]},
                    {"component": "div", "html": (
                        "<div style=\"display:flex;color:#6b7280;font-size:11px;padding:8px 4px 6px;\">"
                        "<span style=\"width:96px;\">分类 / 状态</span>"
                        "<span style=\"flex:1 1 auto;\">本地 STRM 输出目录 ➜ 移动云盘绝对路径</span>"
                        "<span>操作</span></div>"
                    )}
                ] + mapping_row_views,
                },
            ],
        }

        # 右栏：实时日志终端（column-reverse：DOM 最新在前，视觉锚定底部）
        feed_tag_colors = {"MONITOR": "#38bdf8", "STRM-GEN": "#10b981", "PRUNE": "#f59e0b",
                           "POLL": "#60a5fa", "FAIL": "#f43f5e", "TASK": "#34d399",
                           "CONFIG": "#eab308"}
        feed_lines = []
        live_events = self.__live_event_snapshot(40)
        for event in reversed(live_events[-8:]):
            feed_tag = str(event.get("tag") or "EVENT")
            feed_lines.append(
                f"<div><span style=\"color:#6b7280\">[{html_escape(str(event.get('time') or '-'))}]</span> "
                f"<span style=\"color:{feed_tag_colors.get(feed_tag, '#38bdf8')}\">[{html_escape(feed_tag)}]</span> "
                f"<span style=\"color:#e5e7eb\">{html_escape(str(event.get('message') or ''))}</span></div>"
            )
        if not feed_lines:
            # 插件重启后事件缓冲为空时，回退展示最近任务明细
            for item in reversed(latest_items[:8]):
                feed_time = item.get("created_at") or "-"
                item_status = item.get("status") or ""
                item_action = item.get("action") or "-"
                item_reason = item.get("reason") or "-"
                feed_source = self.__shorten_path(item.get("source_file") or "")
                if item_status == "success":
                    feed_tag, feed_color = "STRM-GEN", "#10b981"
                    feed_message = f"生成文件 -> {feed_source}"
                elif item_status == "failed":
                    feed_tag, feed_color = "FAIL", "#f43f5e"
                    feed_message = f"{feed_source} {item_reason}"
                elif item_status == "skipped":
                    feed_tag, feed_color = "SKIP", "#f59e0b"
                    feed_message = f"跳过 {feed_source} {item_reason}"
                else:
                    feed_tag, feed_color = "EVENT", "#38bdf8"
                    feed_message = f"{item_action} {feed_source} {item_reason}"
                feed_lines.append(
                    f"<div><span style=\"color:#6b7280\">[{html_escape(feed_time)}]</span> "
                    f"<span style=\"color:{feed_color}\">[{feed_tag}]</span> "
                    f"<span style=\"color:#e5e7eb\">{html_escape(feed_message)}</span></div>"
                )
        if not feed_lines:
            feed_lines.append("<div><span style=\"color:#6b7280\">暂无同步记录，等待监控事件...</span></div>")
        feed_html = (
            "<div style=\"background:#0b0f19;border:1px solid #1f2937;border-radius:10px;"
            "padding:12px 14px;font-family:Consolas,Monaco,monospace;font-size:12px;"
            "line-height:1.8;overflow:auto;flex:1 1 auto;height:auto;min-height:120px;box-sizing:border-box;"
            "display:flex;flex-direction:column-reverse;\">"
            + "".join(feed_lines) + "</div>"
        )
        feed_card = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-4",
                      "style": dark_card_style + "flex:1 1 auto;display:flex;flex-direction:column;"},
            "content": [
                {"component": "VCardText",
                 "props": {"style": "display:flex;flex-direction:column;flex:1 1 auto;"},
                 "content": [
                    {"component": "div", "html": panel_title(
                        "实时同步任务与运行日志", "Live Log Feed · OpenList + CD2 事件流")},
                    {"component": "div", "props": {"class": "mt-2"}, "html": feed_html},
                ]},
            ],
        }
        page = [{
            "component": "div",
            "props": {"style": "overflow-x:hidden;scrollbar-gutter:stable;width:100%;max-width:100%;"},
            "content": [
            header_card,
            {
                "component": "VRow",
                "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [kpi_card, strategy_card]},
                    {"component": "VCol", "props": {"cols": 12, "md": 8, "class": "d-flex flex-column",
                                        "style": "height:100%;"}, "content": [mapping_card, feed_card]},
                ],
            },
            {"component": "VExpansionPanels", "props": {"variant": "accordion", "class": "mb-4"},
             "content": [
                {"component": "VExpansionPanel", "content": [
                    {"component": "VExpansionPanelTitle", "content": [
                        {"component": "VIcon", "props": {"icon": "mdi-clipboard-text-outline",
                                                          "size": "small", "class": "mr-2"}},
                        {"component": "span", "text": "任务中心与失败重试（扫描进度、历史与明细，点击展开）"},
                    ]},
                    {"component": "VExpansionPanelText", "content": [
                        {
                            "component": "VCard",
                            "props": {"variant": "tonal", "class": "mb-4"},
                            "content": [
                                {"component": "VCardTitle", "text": "任务中心"},
                                {"component": "VCardText", "content": overview_rows},
                    {"component": "VCardActions", "content": [
                        {"component": "VBtn",
                         "props": {"prependIcon": "mdi-play", "color": "primary", "variant": "flat",
                                   "disabled": is_running},
                         "text": "立即全量扫描（运行中）" if is_running else "立即全量扫描",
                         "events": {"click": {"api": f"plugin/{self.__class__.__name__}/tasks",
                                              "method": "POST", "params": {"kind": "full_scan"}}}},
                        {"component": "VBtn", "props": {"prependIcon": "mdi-refresh", "variant": "text"},
                         "text": "刷新任务状态",
                         "events": {"click": {"api": f"plugin/{self.__class__.__name__}/tasks",
                                              "method": "GET", "params": {}}}},
                    ]},
                ],
            },
            {"component": "VCard", "props": {"class": "mb-4"}, "content": [
                {"component": "VCardTitle", "text": "最近任务"},
                {"component": "VCardText", "content": recent_body},
            ]},
            {"component": "VCard", "props": {"class": "mb-4"}, "content": [
                {"component": "VCardTitle", "text": "任务详情"},
                {"component": "VCardText", "content": [
                    {"component": "VAlert", "props": {"type": "info", "variant": "tonal",
                                                      "text": f"当前查看任务 ID：{task_id or '无'}"}},
                ]},
                *([{"component": "VCardActions", "content": detail_actions}] if detail_actions else []),
                {"component": "VCardActions", "content": detail_filters},
                {"component": "div",
                 "html": self.__render_table_html(item_headers, item_rows, "暂无明细数据")},
                *([{"component": "div",
                    "props": {"class": "text-caption text-medium-emphasis mt-1 px-1"},
                    "text": f"仅显示前 100 条，共 {items_total} 条，可点击上方筛选按钮缩小范围"}]
                  if items_total > len(item_rows) else []),
                {"component": "VCardText", "content": [
                    {"component": "VListSubheader", "text": "可重试失败项（支持全部重试或逐项重试）"},
                    failed_block,
                    {"component": "VBtn", "props": {"prependIcon": "mdi-open-in-new", "variant": "text",
                                                    "disabled": not bool(detail_url)},
                     "text": "刷新任务详情",
                     "events": {"click": {"api": detail_url, "method": "GET", "params": {}}}},
                ]},
            ]},
                        ]},
                    ]},
                ],
            },
            ],
        }
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
        is_running = bool(current)
        monitor_rows = self.__monitor_config_rows()
        monitor_status, monitor_color = self.__monitor_status()[:2]
        discovered = stats.get("discovered", 0)
        progress = min(100, round(stats.get("processed", 0) * 100 / max(1, discovered))) if is_running else 0
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
                 "content": [{"component": "VChip", "props": {"color": monitor_color, "variant": "tonal"},
                              "text": f"监控：{monitor_status}"}]},
                {"component": "VCol", "props": {"cols": 6, "md": 2},
                 "content": [{"component": "VChip", "props": {"variant": "tonal"},
                              "text": f"目录 {len(monitor_rows)}"}]},
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
        }]
        if is_running:
            page.append({
                "component": "VRow",
                "content": [{"component": "VCol", "props": {"cols": 12},
                             "content": [{"component": "VProgressLinear", "props": {
                                 "modelValue": progress, "height": 8, "rounded": True,
                                 "color": "primary",
                                 "indeterminate": not bool(discovered)}}]}],
            })
        page.append({
            "component": "div",
            "html": self.__render_table_html(
                [{"title": "时间", "key": "时间"}, {"title": "状态", "key": "状态"},
                 {"title": "成功", "key": "成功"}, {"title": "跳过", "key": "跳过"},
                 {"title": "失败", "key": "失败"}],
                rows, "暂无任务记录"),
        })
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
