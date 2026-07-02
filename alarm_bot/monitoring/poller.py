from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import TYPE_CHECKING

from alarm_bot.bluefors.client import BlueforsApiClient, BlueforsApiError
from alarm_bot.logging.audit import AuditLogger
from alarm_bot.monitoring.alert_manager import AlertManager

if TYPE_CHECKING:
    from alarm_bot.app_context import AppContext

logger = logging.getLogger(__name__)


class MonitorPoller:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="monitor-poller", daemon=True)
        self._thread.start()
        logger.info("Monitor poller started (interval=%ss)", self.ctx.env.poll_interval_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.ctx.env.poll_interval_seconds)

    def poll_once(self) -> None:
        poll_id = str(uuid.uuid4())[:8]
        audit: AuditLogger = self.ctx.audit
        client: BlueforsApiClient = self.ctx.bluefors_client
        alert_mgr: AlertManager = self.ctx.alert_manager

        audit.log("poll.start", payload={"poll_id": poll_id})
        start = time.perf_counter()
        try:
            snapshot = client.fetch_snapshot()
            duration_ms = int((time.perf_counter() - start) * 1000)
            audit.log(
                "poll.success",
                payload={
                    "poll_id": poll_id,
                    "node_count": snapshot.node_count,
                    "duration_ms": duration_ms,
                },
            )
            self.ctx.last_snapshot = snapshot
            alert_mgr.process_snapshot(snapshot)
        except BlueforsApiError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            audit.log(
                "poll.failure",
                payload={"poll_id": poll_id, "error": str(exc), "duration_ms": duration_ms},
            )
            logger.warning("Poll failed: %s", exc)
            if self.ctx.slack_notifier:
                self.ctx.slack_notifier.send_api_error(str(exc))
