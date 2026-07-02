from __future__ import annotations

from datetime import datetime


def format_local_timestamp(dt: datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")
