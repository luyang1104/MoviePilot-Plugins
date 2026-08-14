"""Path mapping and STRM content helpers."""

from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path
from typing import Mapping, Optional, Set, Tuple


def path_key(path: str) -> str:
    """Return a normalized path key for boundary comparisons."""
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


def relative_path(path: str, root: str) -> Optional[Path]:
    """Return path relative to root, or None when path is outside root."""
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


def is_path_within(path: str, root: str) -> bool:
    return relative_path(path, root) is not None


def map_path(path: str, source_root: str, target_root: str) -> Optional[str]:
    """Map a local path from one root to another."""
    if not path or not source_root or not target_root:
        return None
    relative = relative_path(path, source_root)
    if relative is None:
        return None
    if str(relative) in ("", "."):
        return os.path.normpath(str(target_root))
    return os.path.normpath(os.path.join(str(target_root), str(relative)))


def find_monitor_path(file_path: str, monitor_paths: Mapping[str, object]) -> Optional[str]:
    """Return the most specific configured monitor root containing a path."""
    candidates = [
        monitor_path
        for monitor_path in monitor_paths
        if is_path_within(file_path, monitor_path)
    ]
    return max(candidates, key=lambda path: len(path_key(path))) if candidates else None


def map_library_path(paths: Mapping[str, str], file_path: str) -> str:
    """Map a local media path to the configured media-server path."""
    if paths:
        matches = [path for path in paths if is_path_within(file_path, path)]
        if matches:
            library_path = max(matches, key=lambda path: len(path_key(path)))
            relative = relative_path(file_path, library_path)
            target_root = str(paths.get(library_path) or "")
            if relative is not None:
                relative_text = str(relative).replace("\\", "/")
                if target_root.startswith("/"):
                    return target_root.rstrip("/") + "/" + relative_text
                return os.path.normpath(os.path.join(target_root, relative_text))
    return file_path


def normalise_extensions(value: Optional[str], default: str = "") -> Set[str]:
    """Normalize comma-separated extensions into lower-case dotted values."""
    result: Set[str] = set()
    for extension in str(value or default).split(","):
        extension = extension.strip().lower()
        if not extension:
            continue
        result.add(extension if extension.startswith(".") else f".{extension}")
    return result


def parse_mapping_line(line: str) -> Optional[Tuple[str, str]]:
    """Parse source=>target and the legacy colon mapping syntax."""
    value = str(line or "").strip()
    if not value:
        return None

    if "=>" in value:
        source, target = value.split("=>", 1)
    else:
        windows_match = re.match(
            r"^(?P<source>[A-Za-z]:[\\/].*?)(?::)(?P<target>.+)$",
            value,
        )
        if windows_match:
            source = windows_match.group("source")
            target = windows_match.group("target")
        elif ":" in value:
            source, target = value.split(":", 1)
        else:
            return None

    source = source.strip()
    target = target.strip()
    return (source, target) if source and target else None


def serialize_mapping_line(source: str, target: str) -> str:
    return f"{source}=>{target}"


def format_content(
    format_str: Optional[str],
    local_file: str,
    cloud_file: Optional[str],
    uriencode: bool,
) -> Optional[str]:
    """Render a STRM template, returning None for invalid templates."""
    result = str(format_str or "")
    if "{cloud_file}" in result:
        if not cloud_file:
            return None
        cloud_value = (
            urllib.parse.quote(str(cloud_file), safe="")
            if uriencode
            else str(cloud_file).replace("\\", "/")
        )
        result = result.replace("{cloud_file}", cloud_value)
    if "{local_file}" in result:
        result = result.replace("{local_file}", local_file)
    if not any(token in result for token in ("{local_file}", "{cloud_file}")):
        return result
    return None
