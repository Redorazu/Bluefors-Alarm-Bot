from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from alarm_bot.bluefors.models import SystemSnapshot

logger = logging.getLogger(__name__)


class BlueforsApiError(Exception):
    pass


class BlueforsApiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        verify_ssl: bool = False,
        snapshot_branch: str = "",
        snapshot_fields: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.snapshot_branch = snapshot_branch.strip("/")
        self.snapshot_fields = snapshot_fields
        self.timeout = timeout

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"key": self.api_key}
        if extra:
            params.update(extra)
        return params

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = urljoin(self.base_url, path.lstrip("/"))
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=self.timeout) as client:
                response = client.get(url, params=self._params(params))
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise BlueforsApiError(str(exc)) from exc
        if not isinstance(data, dict):
            raise BlueforsApiError("Unexpected API response type")
        if "error" in data:
            err = data["error"]
            raise BlueforsApiError(
                err.get("description", "API error") if isinstance(err, dict) else str(err)
            )
        return data

    def fetch_system_info(self) -> dict[str, Any]:
        data = self._get("system/")
        return data.get("data", data)

    def fetch_snapshot(self) -> SystemSnapshot:
        branch = self.snapshot_branch
        path = f"values/{branch}/" if branch else "values/"
        params: dict[str, Any] = {
            "recursion": -1,
            "style": "flat",
        }
        if self.snapshot_fields:
            params["fields"] = self.snapshot_fields
        data = self._get(path, params)
        nodes = data.get("data", {})
        if not isinstance(nodes, dict):
            raise BlueforsApiError("Snapshot data is not a dict")
        return SystemSnapshot(
            fetched_at=datetime.now(UTC),
            nodes=nodes,
            node_count=len(nodes),
        )

    def fetch_notifications(self) -> list[dict[str, Any]]:
        data = self._get("notifications/")
        payload = data.get("data", data)
        if isinstance(payload, dict):
            notifications = payload.get("notifications", [])
            return notifications if isinstance(notifications, list) else []
        return []

    def health_check(self) -> bool:
        try:
            self.fetch_system_info()
            return True
        except BlueforsApiError:
            return False
