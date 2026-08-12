"""Path and STRM content helpers."""

from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path
from typing import Mapping, Optional, Tuple


def parse_mapping_line(line: str) -> Optional[Tuple[str, str]]:
    """Parse source=>target and the legacy colon syntax."""
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


def shorten_path(path: str, keep: int = 2) -> str:
    """Keep only the last path components for compact UI output."""
    value = str(path or "")
    if not value:
        return ""
    parts = [part for part in re.split(r"[\\/]+", value) if part]
    if len(parts) <= keep:
        return value
    return "\u2026/" + "/".join(parts[-keep:])


def path_key(path: str) -> str:
    """Return a normalized key for path comparisons."""
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


def relative_path(path: str, root: str) -> Optional[Path]:
    """Return path relative to root or None when it is outside root."""
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
    """Map a local path from one root to another without resolving symlinks."""
    relative = relative_path(path, source_root)
    if relative is None:
        return None
    if str(relative) in ("", "."):
        return os.path.normpath(str(target_root))
    return os.path.normpath(os.path.join(str(target_root), str(relative)))


def normalize_extensions(value: Optional[str], default: str = "") -> set[str]:
    """Normalize comma-separated extensions to lower-case values with a dot."""
    result: set[str] = set()
    for extension in str(value or default).split(","):
        extension = extension.strip().lower()
        if not extension:
            continue
        result.add(extension if extension.startswith(".") else "." + extension)
    return result


def join_remote_path(root: str, relative: Path) -> str:
    """Join a remote slash-delimited path with a local relative path."""
    root = str(root or "")
    relative_text = str(relative).replace("\\", "/")
    if not relative_text or relative_text == ".":
        return root
    if not root:
        return "/" + relative_text.lstrip("/")
    return root + relative_text if root.endswith("/") else root + "/" + relative_text


def find_monitor_path(file_path: str, monitor_paths: Mapping[str, object]) -> Optional[str]:
    """Return the most specific configured monitor root containing a path."""
    candidates = [
        monitor_path for monitor_path in monitor_paths
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


def format_content(
    format_str: str,
    local_file: str,
    cloud_file: str,
    uriencode: bool,
) -> Optional[str]:
    """Render a STRM template, returning None for invalid templates."""
    result = str(format_str or "")
    if not any(token in result for token in ("{local_file}", "{cloud_file}")):
        return None
    if "{cloud_file}" in result:
        cloud_value = (
            urllib.parse.quote(cloud_file, safe="")
            if uriencode else cloud_file.replace("\\", "/")
        )
        result = result.replace("{cloud_file}", cloud_value)
    if "{local_file}" in result:
        result = result.replace("{local_file}", local_file)
    return None if any(token in result for token in ("{local_file}", "{cloud_file}")) else result
