from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from alarm_bot.logging.events import EventType
from alarm_bot.paths import BASE_DIR, LOG_DIR

logger = logging.getLogger(__name__)


class AuditLogger:
    def __init__(self, audit_path: Path, rotate_mb: int = 10, backups: int = 30) -> None:
        self.audit_path = audit_path
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._handler = RotatingFileHandler(
            audit_path,
            maxBytes=rotate_mb * 1024 * 1024,
            backupCount=backups,
            encoding="utf-8",
        )
        self._handler.setFormatter(logging.Formatter("%(message)s"))

    def _emit_line(self, line: str) -> None:
        record = logging.LogRecord(
            name="alarm_bot.audit",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=line,
            args=(),
            exc_info=None,
        )
        self._handler.emit(record)

    def close(self) -> None:
        self._handler.close()

    def log(
        self,
        event_type: EventType,
        *,
        alert_id: str | None = None,
        metric_id: str | None = None,
        user_id: str | None = None,
        channel_id: str | None = None,
        thread_ts: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "alert_id": alert_id,
            "metric_id": metric_id,
            "user_id": user_id,
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "payload": payload or {},
        }
        self._emit_line(json.dumps(record, ensure_ascii=False))

    def query(
        self,
        *,
        alert_id: str | None = None,
        metric_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        results: list[dict[str, Any]] = []
        with self.audit_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if alert_id and rec.get("alert_id") != alert_id:
                    continue
                if metric_id and rec.get("metric_id") != metric_id:
                    continue
                if event_type and rec.get("event_type") != event_type:
                    continue
                results.append(rec)
        return results[-limit:]


def setup_app_logging(level: str, app_log_path: Path) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    resolved = app_log_path if app_log_path.is_absolute() else BASE_DIR / app_log_path
    resolved.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    if not any(
        isinstance(h, RotatingFileHandler) and h.baseFilename == str(resolved)
        for h in root.handlers
    ):
        file_handler = RotatingFileHandler(
            resolved, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
