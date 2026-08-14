"""Monitor-rule parsing and validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List, Optional, Tuple

from .core_paths import is_path_within, parse_mapping_line, serialize_mapping_line


@dataclass(frozen=True)
class MonitorRule:
    local_dir: str
    strm_dir: str
    cloud_dir: str
    format_str: str
    monitor_override: Optional[str] = None
    category: Optional[str] = None

    def should_monitor(self, global_monitor: bool) -> bool:
        if self.monitor_override is None:
            return bool(global_monitor)
        return self.monitor_override == "monitor"

    def to_line(self) -> str:
        line = f"{self.local_dir}#{self.strm_dir}#{self.cloud_dir}#{self.format_str}"
        if self.category:
            line += f"@{self.category}"
        if self.monitor_override:
            line += f"${self.monitor_override}"
        return line


def parse_monitor_confs(monitor_confs: Optional[str]) -> Tuple[List[MonitorRule], List[str]]:
    """Parse the legacy local#strm#cloud#format@category$mode syntax."""
    rules: List[MonitorRule] = []
    errors: List[str] = []

    for raw_line in str(monitor_confs or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        monitor_override = None
        if line.count("$") == 1:
            line, monitor_override = line.split("$", 1)
            monitor_override = monitor_override.strip() or None

        category = None
        if line.count("@") == 1:
            line, category = line.split("@", 1)
            category = category.strip() or None

        if line.count("#") < 3:
            errors.append(f"目录配置格式错误：{raw_line.strip()}")
            continue

        local_dir, strm_dir, cloud_dir, format_str = [
            part.strip() for part in line.split("#", 3)
        ]
        if not local_dir or not strm_dir:
            errors.append(f"目录配置缺少本地路径或 STRM 路径：{raw_line.strip()}")
            continue
        if not any(token in format_str for token in ("{local_file}", "{cloud_file}")):
            errors.append(
                f"{local_dir} 的 STRM 模板缺少 {{local_file}} 或 {{cloud_file}}"
            )
            continue
        rules.append(
            MonitorRule(
                local_dir=local_dir,
                strm_dir=strm_dir,
                cloud_dir=cloud_dir,
                format_str=format_str,
                monitor_override=monitor_override,
                category=category,
            )
        )

    valid_rules: List[MonitorRule] = []
    for rule in rules:
        if is_path_within(rule.strm_dir, rule.local_dir):
            errors.append(f"STRM 目录不能位于源目录内：{rule.strm_dir} 是 {rule.local_dir} 的子目录")
        else:
            valid_rules.append(rule)
    return valid_rules, errors


def rules_to_text(rules: List[MonitorRule]) -> str:
    return "\n".join(rule.to_line() for rule in rules)


def parse_path_mappings(value: Optional[str]) -> List[Tuple[str, str]]:
    mappings: List[Tuple[str, str]] = []
    for line in str(value or "").splitlines():
        mapping = parse_mapping_line(line)
        if mapping:
            mappings.append(mapping)
    return mappings


def parse_comma_path_mappings(value: Optional[str]) -> List[Tuple[str, str]]:
    mappings: List[Tuple[str, str]] = []
    for item in str(value or "").split(","):
        mapping = parse_mapping_line(item)
        if mapping:
            mappings.append(mapping)
    return mappings


def serialize_path_mappings(mappings: List[Tuple[str, str]]) -> str:
    return "\n".join(serialize_mapping_line(source, target) for source, target in mappings)


def config_fingerprint(
    rules: List[MonitorRule],
    path_replacements: dict,
    emby_paths: dict,
    media_extensions: set,
    other_extensions: set,
    cover: bool,
    copy_files: bool,
    copy_subtitles: bool,
    uriencode: bool,
    subtitle_extensions: set = None,
) -> str:
    """Fingerprint the settings that affect generated STRM content and sidecars."""
    import hashlib
    import json

    payload = {
        "rules": [asdict(rule) for rule in rules],
        "path_replacements": path_replacements,
        "emby_paths": emby_paths,
        "media_extensions": sorted(media_extensions),
        "other_extensions": sorted(other_extensions),
        "cover": cover,
        "copy_files": copy_files,
        "copy_subtitles": copy_subtitles,
        "uriencode": uriencode,
        "subtitle_extensions": sorted(subtitle_extensions or set()),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
