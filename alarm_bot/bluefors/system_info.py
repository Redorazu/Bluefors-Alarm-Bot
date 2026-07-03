from __future__ import annotations

from typing import Any


def display_system_name(system_info: dict[str, Any] | None, default_system_name: str) -> str:
    if not system_info:
        return default_system_name
    name = str(system_info.get("system_name", "")).strip()
    return name or default_system_name


def display_system_version(system_info: dict[str, Any] | None) -> str:
    if not system_info:
        return "n/a"
    for key in ("sw_version", "system_version", "api_version"):
        val = system_info.get(key)
        text = str(val).strip() if val is not None else ""
        if text:
            return text
    return "n/a"
