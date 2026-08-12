"""Configuration and mapping-rule conversion helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .paths import is_path_within


def count_rule_slots(config: dict) -> int:
    slots = 0
    for key in (config or {}).keys():
        match = re.match(r"^rule_(\d+)_(local|strm)$", str(key))
        if match:
            slots = max(slots, int(match.group(1)) + 1)
    return slots


def remove_rule_config_keys(config: dict):
    """Remove structured rule fields before rewriting a normalized config."""
    for key in list((config or {}).keys()):
        if re.match(r"^rule_\d+_(category|local|strm|cloud|format|monitor|delete)$", str(key)):
            config.pop(key, None)


def category_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value).strip()
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[,\uFF0C\u3001]+", raw) if part.strip()]


def category_string(value: Any) -> str:
    return ",".join(category_list(value))


def rules_from_monitor_confs(monitor_confs: str) -> List[dict]:
    """Parse legacy local#strm#cloud#format@category$0 lines."""
    rules: List[dict] = []
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


def rules_from_config(config: dict) -> List[dict]:
    """Prefer structured fields and fall back to the legacy text mirror."""
    config = config or {}
    rules: List[dict] = []
    structured_slots = count_rule_slots(config)
    structured_authoritative = any(
        _rule_slot_has_content(config, index)
        for index in range(structured_slots)
    )
    for index in range(structured_slots):
        delete_value = config.get(f"rule_{index}_delete")
        if ((isinstance(delete_value, str)
             and delete_value.strip().lower() in {"1", "true", "yes", "on"})
                or delete_value is True):
            continue
        local = str(config.get(f"rule_{index}_local") or "").strip()
        strm = str(config.get(f"rule_{index}_strm") or "").strip()
        if not local and not strm:
            continue
        monitor_value = config.get(f"rule_{index}_monitor")
        rules.append({
            "category": category_string(config.get(f"rule_{index}_category") or ""),
            "local": local,
            "strm": strm,
            "cloud": str(config.get(f"rule_{index}_cloud") or "").strip(),
            "format": str(config.get(f"rule_{index}_format") or "").strip(),
            "monitor": bool(monitor_value) if monitor_value is not None else True,
        })
    if rules or structured_authoritative:
        return rules
    return rules_from_monitor_confs(config.get("monitor_confs") or "")


def _rule_slot_has_content(config: dict, index: int) -> bool:
    """Whether a structured slot carries a value or an explicit delete flag."""
    delete_value = config.get(f"rule_{index}_delete")
    if ((isinstance(delete_value, str)
         and delete_value.strip().lower() in {"1", "true", "yes", "on"})
            or delete_value is True):
        return True
    return bool(str(config.get(f"rule_{index}_local") or "").strip()
            or str(config.get(f"rule_{index}_strm") or "").strip())


def rules_to_monitor_confs(rules: List[dict]) -> str:
    lines = []
    for rule in rules or []:
        local = str(rule.get("local") or "").strip()
        strm = str(rule.get("strm") or "").strip()
        if not local and not strm:
            continue
        line = f"{local}#{strm}#{str(rule.get('cloud') or '').strip()}#{str(rule.get('format') or '').strip()}"
        category = category_string(rule.get("category"))
        if category:
            line += f"@{category}"
        if not rule.get("monitor", True):
            line += "$0"
        lines.append(line)
    return "\n".join(lines)


def rules_to_config_keys(rules: List[dict], slots: int) -> Dict[str, Any]:
    keys: Dict[str, Any] = {}
    for index in range(max(slots, len(rules or []))):
        rule = rules[index] if rules and index < len(rules) else {}
        keys[f"rule_{index}_category"] = category_string(rule.get("category"))
        keys[f"rule_{index}_local"] = str(rule.get("local") or "")
        keys[f"rule_{index}_strm"] = str(rule.get("strm") or "")
        keys[f"rule_{index}_cloud"] = str(rule.get("cloud") or "")
        keys[f"rule_{index}_format"] = str(rule.get("format") or "")
        keys[f"rule_{index}_monitor"] = bool(rule.get("monitor", True)) if rule else True
    return keys


def validate_monitor_confs(monitor_confs: str) -> List[str]:
    """Validate mapping syntax without touching the filesystem."""
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
        if is_path_within(strm_dir, local_dir) or is_path_within(local_dir, strm_dir):
            errors.append(f"目录配置存在包含关系：{local_dir} 与 {strm_dir}")
            continue
        if not any(token in format_str for token in ("{local_file}", "{cloud_file}")):
            errors.append(f"{local_dir} 格式化模板缺少 {{local_file}} 或 {{cloud_file}}")
    return errors
